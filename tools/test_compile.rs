// Small test to verify compile_line behavior with body_trimmed
fn main() {
    let body_trimmed = "S k=\"\" F S k=$O(^A(t,k)) Q:k=\"\" D\n  S i=i+1\n  S ^R(i)=^A(t,k)";
    println!("body_trimmed len={}", body_trimmed.len());
    println!("body_trimmed={:?}", body_trimmed);
    
    // Simulate compile_line processing
    let mut rest = body_trimmed.trim();
    println!("rest (initial) len={}: {:?}", rest.len(), &rest[..rest.len().min(60)]);
    
    // After SET k=""
    // Find first whitespace
    let token_end = rest.find(char::is_whitespace).unwrap_or(rest.len());
    let raw_token = &rest[..token_end];
    println!("token 0={:?} end={}", raw_token, token_end);
    
    let after_token = rest[token_end..].trim_start();
    println!("after_token (SET) len={}: {:?}", after_token.len(), &after_token[..after_token.len().min(80)]);
}
