//! LUMEN Level 2 — Zero-Copy Shared Memory Transport
//!
//! Two unidirectional lock-free SPSC ring buffers in a single shared
//! memory region (512 KiB default). Header (128B) contains magic,
//! version, layout info, and atomic cursors for both rings.
//!
//! Ring A: Client → Server   |   Ring B: Server → Client

use std::io;
use std::sync::atomic::{AtomicU64, Ordering};

// ── Constants ────────────────────────────────────────────────────────

const SHM_MAGIC: u32 = 0x4C554D45; // "LUME"
const SHM_VERSION: u32 = 1;
const DEFAULT_REGION_SIZE: usize = 512 * 1024; // 512 KiB
const HEADER_SIZE: usize = 128;

/// Maximum spin iterations before declaring a peer-dead timeout.
const MAX_SPIN: u32 = 1_000_000;
/// Every this many spins, call `thread::yield_now()` for better behavior.
const YIELD_INTERVAL: u32 = 1000;

// ── Error type ──────────────────────────────────────────────────────

/// Error type for SHM ring buffer operations.
#[derive(Debug)]
pub struct ShmError(String);

impl std::fmt::Display for ShmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for ShmError {}

impl From<ShmError> for io::Error {
    fn from(e: ShmError) -> Self {
        io::Error::new(io::ErrorKind::TimedOut, e.0)
    }
}

// ── Header (must be #[repr(C)] for cross-process agreement) ──────────

#[repr(C)]
struct ShmHeader {
    magic: u32,
    version: u32,
    data_offset: u64,   // = HEADER_SIZE
    data_len: u64,       // total data region size
    mid: u64,            // split point between ring A and B

    // Ring A — Client→Server
    write_a: AtomicU64,
    read_a: AtomicU64,

    // Ring B — Server→Client
    write_b: AtomicU64,
    read_b: AtomicU64,

    _pad: [u8; 40],      // to 128 bytes cache-line aligned
}

unsafe impl Send for ShmHeader {}
unsafe impl Sync for ShmHeader {}

impl ShmHeader {
    fn init(&self, region_size: u64) {
        let p = self as *const ShmHeader as *mut ShmHeader;
        let data_len = region_size - HEADER_SIZE as u64;
        unsafe {
            (*p).magic = SHM_MAGIC;
            (*p).version = SHM_VERSION;
            (*p).data_offset = HEADER_SIZE as u64;
            (*p).data_len = data_len;
            (*p).mid = HEADER_SIZE as u64 + data_len / 2;
        }
        self.write_a.store(0, Ordering::Release);
        self.read_a.store(0, Ordering::Release);
        self.write_b.store(0, Ordering::Release);
        self.read_b.store(0, Ordering::Release);
    }

    fn validate(&self) -> bool {
        self.magic == SHM_MAGIC && self.version == SHM_VERSION
    }
}

// ── Ring side ────────────────────────────────────────────────────────

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum RingSide { A, B }

// ── Ring buffer ──────────────────────────────────────────────────────

/// Lock-free SPSC (single-producer single-consumer) ring buffer
/// backed by shared memory. Only one writer and one reader per side.
pub struct ShmRingBuffer {
    header: *const ShmHeader,
    data_base: *mut u8,
    side: RingSide,
}

unsafe impl Send for ShmRingBuffer {}
unsafe impl Sync for ShmRingBuffer {}

impl ShmRingBuffer {
    /// Create from an already-mapped region.
    /// # Safety
    /// `region_ptr` must point to initialized shared memory >= region_size.
    pub unsafe fn from_raw(region_ptr: *mut u8, _sz: usize, side: RingSide) -> Self {
        Self {
            header: region_ptr as *const ShmHeader,
            data_base: region_ptr.add(HEADER_SIZE),
            side,
        }
    }

    /// Initialize the header of a freshly-created region.
    pub fn init_region(ptr: *mut u8, size: usize) {
        unsafe { &*(ptr as *const ShmHeader) }.init(size as u64);
        unsafe { std::ptr::write_bytes(ptr.add(HEADER_SIZE), 0, size - HEADER_SIZE); }
    }

    // ── helpers ──
    fn hdr(&self) -> &ShmHeader { unsafe { &*self.header } }

    fn wcur(&self) -> &AtomicU64 {
        match self.side {
            RingSide::A => &self.hdr().write_a,
            RingSide::B => &self.hdr().write_b,
        }
    }

    fn rcur(&self) -> &AtomicU64 {
        match self.side {
            RingSide::A => &self.hdr().read_a,
            RingSide::B => &self.hdr().read_b,
        }
    }

    fn rng_start(&self) -> u64 {
        let h = self.hdr();
        match self.side { RingSide::A => h.data_offset, RingSide::B => h.mid }
    }

    fn rng_end(&self) -> u64 {
        let h = self.hdr();
        match self.side { RingSide::A => h.mid, RingSide::B => h.data_offset + h.data_len }
    }

    fn rng_len(&self) -> u64 { self.rng_end() - self.rng_start() }
    // ── Write ────────────────────────────────────────────────────
    /// Write data. Spins if ring is full (up to MAX_SPIN iterations).
    /// Returns `Ok(bytes_written)` or `Err(ShmError)` on timeout.
    pub fn write(&self, data: &[u8]) -> Result<usize, ShmError> {
        let start = self.rng_start();
        let len = self.rng_len();
        let cap = len - 1; // one byte reserved to distinguish full/empty
        let mut written = 0usize;
        let mut spins: u32 = 0;
        while written < data.len() {
            let w = self.wcur().load(Ordering::Acquire);
            let r = self.rcur().load(Ordering::Acquire);
            let used = if w >= r { w - r } else { w + len - r };
            let avail = cap.saturating_sub(used);
            if avail == 0 {
                spins += 1;
                if spins >= MAX_SPIN {
                    return Err(ShmError(
                        "SHM ring buffer timeout: write peer appears dead".into(),
                    ));
                }
                std::hint::spin_loop();
                if spins % YIELD_INTERVAL == 0 {
                    std::thread::yield_now();
                }
                continue;
            }
            spins = 0; // made progress, reset counter
            let n = ((data.len() - written) as u64).min(avail);
            let wabs = start + (w % len);
            let c1 = n.min(start + len - wabs);
            unsafe {
                let dst = self.data_base.offset((wabs - HEADER_SIZE as u64) as isize);
                std::ptr::copy_nonoverlapping(data.as_ptr().add(written), dst, c1 as usize);
                if c1 < n {
                    let src2 = data.as_ptr().add(written + c1 as usize);
                    let dst2 = self.data_base.offset((start - HEADER_SIZE as u64) as isize);
                    std::ptr::copy_nonoverlapping(src2, dst2, (n - c1) as usize);
                }
            }
            let nw = if w + n >= len { w + n - len } else { w + n };
            self.wcur().store(nw, Ordering::Release);
            written += n as usize;
        }
        Ok(written)
    }

    /// Write a length-prefixed frame (4-byte LE length + data).
    pub fn write_frame(&self, data: &[u8]) -> Result<(), ShmError> {
        self.write(&(data.len() as u32).to_le_bytes())?;
        self.write(data)?;
        Ok(())
    }

    // ── Read ─────────────────────────────────────────────────────
    /// Read available data. Returns 0 if ring is empty.
    pub fn read(&self, buf: &mut [u8]) -> usize {
        let start = self.rng_start();
        let len = self.rng_len();
        let w = self.wcur().load(Ordering::Acquire);
        let r = self.rcur().load(Ordering::Acquire);
        if w == r { return 0; }
        let avail = if w > r { w - r } else { w + len - r };
        let n = avail.min(buf.len() as u64);
        let rabs = start + (r % len);
        let c1 = n.min(start + len - rabs);
        unsafe {
            let src = (self.data_base as *const u8).offset((rabs - HEADER_SIZE as u64) as isize);
            std::ptr::copy_nonoverlapping(src, buf.as_mut_ptr(), c1 as usize);
            if c1 < n {
                let src2 = self.data_base.offset((start - HEADER_SIZE as u64) as isize);
                std::ptr::copy_nonoverlapping(src2, buf.as_mut_ptr().add(c1 as usize), (n - c1) as usize);
            }
        }
        let nr = if r + n >= len { r + n - len } else { r + n };
        self.rcur().store(nr, Ordering::Release);
        n as usize
    }

    /// Read a complete length-prefixed frame. Returns `Ok(len)` or `Err(ShmError)` on timeout.
    pub fn read_frame(&self, buf: &mut Vec<u8>) -> Result<usize, ShmError> {
        let mut lb = [0u8; 4];
        if self.read(&mut lb) < 4 {
            return Err(ShmError("SHM ring buffer: no frame header available".into()));
        }
        let flen = u32::from_le_bytes(lb) as usize;
        buf.clear();
        buf.resize(flen, 0);
        let mut total = 0;
        let mut spins: u32 = 0;
        while total < flen {
            let n = self.read(&mut buf[total..]);
            if n == 0 {
                spins += 1;
                if spins >= MAX_SPIN {
                    return Err(ShmError(
                        "SHM ring buffer timeout: read peer appears dead".into(),
                    ));
                }
                std::hint::spin_loop();
                if spins % YIELD_INTERVAL == 0 {
                    std::thread::yield_now();
                }
                continue;
            }
            spins = 0; // made progress, reset counter
            total += n;
        }
        Ok(flen)
    }

    /// Bytes available for reading (non-blocking).
    pub fn available(&self) -> u64 {
        let w = self.wcur().load(Ordering::Acquire);
        let r = self.rcur().load(Ordering::Acquire);
        let len = self.rng_len();
        if w >= r { w - r } else { w + len - r }
    }
}

// ── Platform abstraction ─────────────────────────────────────────────

/// A mapped shared memory region. On drop, unmaps and cleans up.
pub struct ShmRegion {
    ptr: *mut u8,
    size: usize,
    inner: ShmInner,
}

enum ShmInner {
    #[cfg(windows)]
    Windows { map_handle: isize },
    #[cfg(all(unix, not(target_arch = "wasm32")))]
    Unix {
        shm_fd: std::os::unix::io::RawFd,
        shm_name: Option<String>,
    },
    #[cfg(target_arch = "wasm32")]
    Wasm,
}

impl ShmRegion {
    /// Create a new shared memory region (server side).
    pub fn create(name: Option<&str>, size: Option<usize>) -> io::Result<Self> {
        Self::create_impl(name, size.unwrap_or(DEFAULT_REGION_SIZE))
    }

    /// Open an existing region by name (client side).
    pub fn open(name: &str, size: Option<usize>) -> io::Result<Self> {
        Self::open_impl(name, size.unwrap_or(DEFAULT_REGION_SIZE))
    }

    pub fn as_ptr(&self) -> *mut u8 { self.ptr }
    pub fn size(&self) -> usize { self.size }

    /// Initialize header for a freshly-created region.
    pub fn init_header(&self) {
        ShmRingBuffer::init_region(self.ptr, self.size);
    }

    /// Create a ring buffer for the given side.
    pub fn ring_buffer(&self, side: RingSide) -> ShmRingBuffer {
        unsafe { ShmRingBuffer::from_raw(self.ptr, self.size, side) }
    }

    /// Check that the header magic and version are valid.
    pub fn validate(&self) -> bool {
        unsafe { &*(self.ptr as *const ShmHeader) }.validate()
    }
    // ──  Windows  ──────────────────────────────────────────────────
    #[cfg(windows)]
    fn create_impl(name: Option<&str>, region_size: usize) -> io::Result<Self> {
        use std::ffi::OsStr;
        use std::os::windows::ffi::OsStrExt;
        let wide: Vec<u16> = match name {
            Some(n) => { let mut v: Vec<u16> = OsStr::new(n).encode_wide().collect(); v.push(0); v }
            None => vec![0u16],
        };
        let name_ptr = if name.is_some() { wide.as_ptr() } else { std::ptr::null() };
        extern "system" {
            fn CreateFileMappingW(f: isize, a: *const u8, p: u32, h: u32, l: u32, n: *const u16) -> isize;
            fn MapViewOfFile(h: isize, a: u32, oh: u32, ol: u32, s: usize) -> *mut u8;
            fn CloseHandle(h: isize) -> i32;
        }
        const PAGE_READWRITE: u32 = 0x04;
        const FILE_MAP_WRITE: u32 = 0x02;
        const INVALID_HANDLE_VALUE: isize = -1;
        let h = unsafe {
            CreateFileMappingW(INVALID_HANDLE_VALUE, std::ptr::null(), PAGE_READWRITE, 0, region_size as u32, name_ptr)
        };
        if h == 0 || h == INVALID_HANDLE_VALUE { return Err(io::Error::last_os_error()); }
        let ptr = unsafe { MapViewOfFile(h, FILE_MAP_WRITE, 0, 0, region_size) };
        if ptr.is_null() { unsafe { CloseHandle(h); }; return Err(io::Error::last_os_error()); }
        Ok(Self { ptr, size: region_size, inner: ShmInner::Windows { map_handle: h } })
    }

    #[cfg(windows)]
    fn open_impl(name: &str, region_size: usize) -> io::Result<Self> {
        use std::ffi::OsStr;
        use std::os::windows::ffi::OsStrExt;
        let mut wide: Vec<u16> = OsStr::new(name).encode_wide().collect(); wide.push(0);
        extern "system" {
            fn OpenFileMappingW(a: u32, i: i32, n: *const u16) -> isize;
            fn MapViewOfFile(h: isize, a: u32, oh: u32, ol: u32, s: usize) -> *mut u8;
            fn CloseHandle(h: isize) -> i32;
        }
        const FILE_MAP_WRITE: u32 = 0x02;
        let h = unsafe { OpenFileMappingW(FILE_MAP_WRITE, 0, wide.as_ptr()) };
        if h == 0 { return Err(io::Error::last_os_error()); }
        let ptr = unsafe { MapViewOfFile(h, FILE_MAP_WRITE, 0, 0, region_size) };
        if ptr.is_null() { unsafe { CloseHandle(h); }; return Err(io::Error::last_os_error()); }
        Ok(Self { ptr, size: region_size, inner: ShmInner::Windows { map_handle: h } })
    }

    // ──  Unix (Linux / macOS)  ─────────────────────────────────────

    #[cfg(all(unix, not(target_arch = "wasm32")))]
    fn create_impl(name: Option<&str>, region_size: usize) -> io::Result<Self> {
        use std::ffi::CString;

        let shm_name = name.unwrap_or("/lumen-shm").to_string();
        let cname = CString::new(shm_name.as_str()).unwrap();

        let fd = unsafe { libc::shm_open(cname.as_ptr(), libc::O_CREAT | libc::O_RDWR | libc::O_EXCL, 0o600) };
        if fd < 0 { return Err(io::Error::last_os_error()); }

        if unsafe { libc::ftruncate(fd, region_size as libc::off_t) } < 0 {
            unsafe { libc::close(fd); libc::shm_unlink(cname.as_ptr()); }
            return Err(io::Error::last_os_error());
        }

        let ptr = unsafe {
            libc::mmap(std::ptr::null_mut(), region_size, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0)
        };
        if ptr == libc::MAP_FAILED {
            unsafe { libc::close(fd); libc::shm_unlink(cname.as_ptr()); }
            return Err(io::Error::last_os_error());
        }

        Ok(Self { ptr: ptr as *mut u8, size: region_size, inner: ShmInner::Unix { shm_fd: fd, shm_name: Some(shm_name) } })
    }

    #[cfg(all(unix, not(target_arch = "wasm32")))]
    fn open_impl(name: &str, region_size: usize) -> io::Result<Self> {
        use std::ffi::CString;

        let cname = CString::new(name).unwrap();

        let fd = unsafe { libc::shm_open(cname.as_ptr(), libc::O_RDWR, 0o600) };
        if fd < 0 { return Err(io::Error::last_os_error()); }

        let ptr = unsafe {
            libc::mmap(std::ptr::null_mut(), region_size, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0)
        };
        if ptr == libc::MAP_FAILED {
            unsafe { libc::close(fd); }
            return Err(io::Error::last_os_error());
        }

        Ok(Self { ptr: ptr as *mut u8, size: region_size, inner: ShmInner::Unix { shm_fd: fd, shm_name: None } })
    }

    // ──  WASM stub  ─────────────────────────────────────────────────
    #[cfg(target_arch = "wasm32")]
    fn create_impl(_name: Option<&str>, _size: usize) -> io::Result<Self> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "Level 2 shm not supported on wasm32"))
    }

    #[cfg(target_arch = "wasm32")]
    fn open_impl(_name: &str, _size: usize) -> io::Result<Self> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "Level 2 shm not supported on wasm32"))
    }
}

// ── Drop ────────────────────────────────────────────────────────────

impl Drop for ShmRegion {
    fn drop(&mut self) {
        unsafe {
            match &self.inner {
                #[cfg(windows)]
                ShmInner::Windows { map_handle } => {
                    extern "system" {
                        fn UnmapViewOfFile(ptr: *const u8) -> i32;
                        fn CloseHandle(h: isize) -> i32;
                    }
                    UnmapViewOfFile(self.ptr);
                    CloseHandle(*map_handle);
                }
                #[cfg(all(unix, not(target_arch = "wasm32")))]
                ShmInner::Unix { shm_fd, shm_name } => {
                    libc::munmap(self.ptr as *mut libc::c_void, self.size);
                    libc::close(*shm_fd);
                    if let Some(ref name) = shm_name {
                        let cname = std::ffi::CString::new(name.as_str()).unwrap();
                        libc::shm_unlink(cname.as_ptr());
                    }
                }
                #[cfg(target_arch = "wasm32")]
                ShmInner::Wasm => {}
            }
        }
    }
}
