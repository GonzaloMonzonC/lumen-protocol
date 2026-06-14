<?php
declare(strict_types=1);
$autoloadPath = __DIR__ . '/vendor/autoload.php';
require file_exists($autoloadPath) ? $autoloadPath : __DIR__ . '/autoload_manual.php';
use Lumen\Compress, Lumen\Dict, Lumen\Frame, Lumen\FrameAssembler, Lumen\Hyb128;
define('TYPE_REQUEST', 1);
function timeit(int $runs, callable $fn, int $warmup = 0): float {
    for ($i = 0; $i < $warmup; $i++) $fn();
    $t0 = hrtime(true);
    for ($i = 0; $i < $runs; $i++) $fn();
    return (hrtime(true) - $t0) / 1e6;
}
function makeResult(string $name, string $category, int $ops, float $durationMs, int $bytesProcessed = 0, array $extra = []): array {
    $opsPerSec = $durationMs > 0 ? (int)round($ops / ($durationMs / 1000)) : 0;
    $bytesPerSec = $durationMs > 0 ? (int)round($bytesProcessed / ($durationMs / 1000)) : 0;
    return ['name'=>$name,'category'=>$category,'ops'=>$ops,'durationMs'=>round($durationMs,2),'opsPerSec'=>$opsPerSec,'bytesProcessed'=>$bytesProcessed,'bytesPerSec'=>$bytesPerSec,'extra'=>$extra];
}
$MCP = [
  ['name'=>'initialize','obj'=>['jsonrpc'=>'2.0','id'=>1,'method'=>'initialize','params'=>['protocolVersion'=>'2024-11-05','capabilities'=>new stdClass(),'clientInfo'=>['name'=>'lumen-test','version'=>'1.0']]]],
  ['name'=>'tools_list','obj'=>['jsonrpc'=>'2.0','id'=>2,'result'=>['tools'=>[
    ['name'=>'read','description'=>'Read file','inputSchema'=>['type'=>'object','properties'=>['path'=>['type'=>'string']],'required'=>['path']]],
    ['name'=>'write','description'=>'Write file','inputSchema'=>['type'=>'object','properties'=>['path'=>['type'=>'string'],'content'=>['type'=>'string']],'required'=>['path','content']]],
    ['name'=>'delete','description'=>'Delete file','inputSchema'=>['type'=>'object','properties'=>['path'=>['type'=>'string']],'required'=>['path']]],
    ['name'=>'execute','description'=>'Execute command','inputSchema'=>['type'=>'object','properties'=>['command'=>['type'=>'string'],'arguments'=>['type'=>'array']],'required'=>['command']]],
    ['name'=>'search','description'=>'Search files','inputSchema'=>['type'=>'object','properties'=>['query'=>['type'=>'string'],'path'=>['type'=>'string']],'required'=>['query']]],
  ]]]],
  ['name'=>'llm_request','obj'=>['model'=>'gpt-4','temperature'=>0.7,'max_tokens'=>4096,'messages'=>[['role'=>'system','content'=>'You are helpful.'],['role'=>'user','content'=>'Explain LUMEN protocol.']],'tools'=>[['type'=>'function','function'=>['name'=>'search','description'=>'Search web','parameters'=>['type'=>'object','properties'=>['query'=>['type'=>'string']]]]]]]],
  ['name'=>'error_response','obj'=>['jsonrpc'=>'2.0','id'=>5,'error'=>['code'=>-32601,'message'=>'Method not found','data'=>['method'=>'unknown_tool','severity'=>'error','details'=>'The requested tool does not exist']]]],
  ['name'=>'big_result','obj'=>['jsonrpc'=>'2.0','id'=>8,'result'=>['content'=>[['type'=>'text','text'=>str_repeat('A',5000)]],'usage'=>['prompt_tokens'=>120,'completion_tokens'=>5000,'total_tokens'=>5120],'model'=>'deepseek-v4','finish_reason'=>'stop']]],
];
function benchAssembler(): array {
    $payloads = ['tiny'=>16,'small'=>256,'medium'=>4096,'large'=>65536,'xlarge'=>262144];
    $results = [];
    foreach ($payloads as $label=>$size) {
        $payload = str_repeat('A',$size);
        $wire = Frame::buildWire(TYPE_REQUEST, 0, $payload);
        $wireLen = strlen($wire);
        foreach ([1,16,64,256,1024,4096,null] as $chunkHint) {
            $acs = $chunkHint??$wireLen;
            $numChunks = (int)ceil($wireLen/$acs);
            // Skip extreme: more than 2000 chunks is unreasonably slow
            if ($numChunks > 2000) continue;
            $csl = $chunkHint===null?'full':(string)$chunkHint;
            $chunks = [];
            for ($i=0;$i<$wireLen;$i+=$acs) $chunks[]=substr($wire,$i,min($acs,$wireLen-$i));
            $runs = $size>16384?100:500;
            // If many chunks, reduce runs
            if ($numChunks > 500) $runs = max(10, (int)($runs * 500 / $numChunks));
            for ($w=0;$w<min(5,$runs);$w++) { $a=new FrameAssembler(); foreach ($chunks as $c) $a->push($c); }
            $fn = function()use($chunks){ $a=new FrameAssembler(); foreach ($chunks as $c) $a->push($c); };
            $ms = timeit($runs,$fn);
            $results[]=makeResult("FrameAssembler {$label}({$size}B) chunk={$csl}",'assembler',$runs,$ms,$wireLen*$runs,['payloadSize'=>$size,'chunkSize'=>$csl==='full'?'full':$acs,'numChunks'=>count($chunks)]);
        }
    }
    return $results;
}
function benchCompression(): array {
    global $MCP; $results = [];
    foreach ($MCP as $e) {
        $name=$e['name']; $obj=$e['obj'];
        $jsonBytes = strlen(json_encode($obj,JSON_UNESCAPED_UNICODE));
        $fn = function()use($obj){ Compress::compress($obj); };
        $ms = timeit(1000,$fn,50);
        $compressed = Compress::compress($obj);
        $cb = strlen($compressed);
        $results[]=makeResult("Compress {$name}",'compression',1000,$ms,$jsonBytes*1000,['objectName'=>$name,'jsonBytes'=>$jsonBytes,'compressedBytes'=>$cb,'ratioPercent'=>round($cb/$jsonBytes*100,1),'savedBytes'=>$jsonBytes-$cb]);
    }
    return $results;
}
function benchHyb128(): array {
    $vals=[0,1,31,63,64,255,1000,65535,65536,100000,1000000];
    $results=[];
    foreach ($vals as $v) {
        $buf=str_repeat("\0",11);
        $fn=function()use($v,&$buf){ Hyb128::encode($v,$buf,0); };
        $ms=timeit(100000,$fn,500);
        $mode=$v<=63?'00':($v<=65535?'10':'11');
        $results[]=makeResult("encodeHyb128({$v})",'hyb128_encode',100000,$ms,extra:['value'=>$v,'mode'=>$mode]);
    }
    foreach ($vals as $v) {
        $enc=Hyb128::encodeBytes($v);
        $fn=function()use($enc){ Hyb128::decode($enc,0); };
        $ms=timeit(100000,$fn,500);
        $results[]=makeResult("decodeHyb128({$v})",'hyb128_decode',100000,$ms,extra:['value'=>$v,'headerBytes'=>strlen($enc)]);
    }
    return $results;
}
function benchDict(): array {
    $keys=['tool','arguments','result','error','id','name','description','content','text','type','method','params','jsonrpc','data','code','message'];
    $N=1000000;
    $fn=function()use($keys,$N){ for($i=0;$i<$N;$i++) Dict::lookup($keys[$i%count($keys)]); };
    $ms=timeit(1,$fn);
    return [makeResult('dict_lookup O(1)','dict',$N,$ms,extra:['totalKeys'=>count($keys)])];
}
function benchEncode(): array {
    global $MCP; $results=[];
    foreach ($MCP as $e) {
        $name=$e['name']; $obj=$e['obj'];
        $jsonStr=json_encode($obj,JSON_UNESCAPED_UNICODE);
        $jsonBytes=strlen($jsonStr);
        $comp=Compress::compress($obj);
        $jsonFn=function()use($obj){ json_encode($obj,JSON_UNESCAPED_UNICODE); };
        $jms=timeit(5000,$jsonFn,50);
        $jops=$jms>0?(int)round(5000/($jms/1000)):0;
        $lumenFn=function()use($obj){ Compress::compress($obj); };
        $lms=timeit(5000,$lumenFn,50);
        $lops=$lms>0?(int)round(5000/($lms/1000)):0;
        $speedup=$jops>0?round($lops/$jops,2):0;
        $results[]=makeResult("Encode json_encode {$name}",'json_encode',5000,$jms,$jsonBytes*5000,['objectName'=>$name,'jsonBytes'=>$jsonBytes]);
        $results[]=makeResult("Encode compress_value {$name}",'lumen_encode',5000,$lms,strlen($comp)*5000,['objectName'=>$name,'compressedBytes'=>strlen($comp),'speedupVsJson'=>$speedup]);
    }
    return $results;
}
function benchDecode(): array {
    global $MCP;
    $prepared=[];
    foreach ($MCP as $e) $prepared[]=['name'=>$e['name'],'js'=>json_encode($e['obj'],JSON_UNESCAPED_UNICODE),'comp'=>Compress::compress($e['obj'])];
    $results=[];
    foreach ($prepared as $p) {
        $name=$p['name']; $js=$p['js']; $comp=$p['comp'];
        $jsonBytes=strlen($js);
        $jsonFn=function()use($js){ json_decode($js,true); };
        $jms=timeit(5000,$jsonFn,50);
        $jops=$jms>0?(int)round(5000/($jms/1000)):0;
        $lumenFn=function()use($comp){ Compress::decompress($comp); };
        $lms=timeit(5000,$lumenFn,50);
        $lops=$lms>0?(int)round(5000/($lms/1000)):0;
        $speedup=$jops>0?round($lops/$jops,2):0;
        $results[]=makeResult("Decode json_decode {$name}",'json_decode',5000,$jms,$jsonBytes*5000,['objectName'=>$name,'jsonBytes'=>$jsonBytes]);
        $results[]=makeResult("Decode decompress_value {$name}",'lumen_decode',5000,$lms,strlen($comp)*5000,['objectName'=>$name,'compressedBytes'=>strlen($comp),'speedupVsJson'=>$speedup]);
    }
    return $results;
}
function benchRoundtrip(): array {
    global $MCP; $results=[];
    foreach ($MCP as $e) {
        $name=$e['name']; $obj=$e['obj'];
        $jsonStr=json_encode($obj,JSON_UNESCAPED_UNICODE);
        $jsonBytes=strlen($jsonStr);
        $comp=Compress::compress($obj);
        $jsonFn=function()use($obj){ json_decode(json_encode($obj,JSON_UNESCAPED_UNICODE),true); };
        $jms=timeit(5000,$jsonFn,50);
        $jops=$jms>0?(int)round(5000/($jms/1000)):0;
        $lumenFn=function()use($obj){ Compress::decompress(Compress::compress($obj)); };
        $lms=timeit(5000,$lumenFn,50);
        $lops=$lms>0?(int)round(5000/($lms/1000)):0;
        $speedup=$jops>0?round($lops/$jops,2):0;
        $results[]=makeResult("Roundtrip JSON {$name}",'json_roundtrip',5000,$jms,$jsonBytes*2*5000,['objectName'=>$name,'jsonBytes'=>$jsonBytes]);
        $results[]=makeResult("Roundtrip LUMEN {$name}",'lumen_roundtrip',5000,$lms,strlen($comp)*2*5000,['objectName'=>$name,'compressedBytes'=>strlen($comp),'speedupVsJson'=>$speedup]);
    }
    return $results;
}
function benchFraming(): array {
    $testVals=[0,42,255,1024,65535,65536,100000,1000000];
    $results=[];
    foreach ($testVals as $v) {
        $cl="Content-Length: {$v}\r\n\r\n";
        $clFn=function()use($cl){
            $prefix='Content-Length: ';
            if(!str_starts_with($cl,$prefix)) return null;
            $end=strpos($cl,"\r\n",strlen($prefix));
            if($end===false) return null;
            return (int)substr($cl,strlen($prefix),$end-strlen($prefix));
        };
        $ms=timeit(500000,$clFn,100);
        $results[]=makeResult("Framing Content-Length({$v})",'framing_cl',500000,$ms,strlen($cl)*500000,['headerValue'=>$v,'headerBytes'=>strlen($cl)]);
        $enc=Hyb128::encodeBytes($v);
        $hybFn=function()use($enc){ Hyb128::decode($enc,0); };
        $ms=timeit(500000,$hybFn,100);
        $results[]=makeResult("Framing Hyb128({$v})",'framing_hyb128',500000,$ms,strlen($enc)*500000,['headerValue'=>$v,'headerBytes'=>strlen($enc)]);
    }
    return $results;
}

$all=[];
$benchmarks=[
    ['assembler','benchAssembler'],
    ['compression','benchCompression'],
    ['hyb128','benchHyb128'],
    ['dict','benchDict'],
    ['encode','benchEncode'],
    ['decode','benchDecode'],
    ['roundtrip','benchRoundtrip'],
    ['framing','benchFraming'],
];
$total=count($benchmarks);
foreach ($benchmarks as $i=>[$name,$fn]) {
    fprintf(STDERR,"[%d/%d] Running %s...\n",$i+1,$total,$name);
    try {
        $res=$fn();
        $all=array_merge($all,$res);
        fprintf(STDERR,"       %d results\n",count($res));
    } catch (\Throwable $e) {
        fprintf(STDERR,"       SKIPPED: %s\n",$e->getMessage());
    }
}
$report=[
    'timestamp'=>date('Y-m-d\TH:i:s'),
    'platform'=>php_uname(),
    'phpVersion'=>PHP_VERSION,
    'results'=>$all,
];
echo json_encode($report,JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT)."\n";
fprintf(STDERR,"\nDone. %d total results.\n",count($all));
