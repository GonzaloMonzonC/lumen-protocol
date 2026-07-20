// Transpilado de M → Rust
// Source: ; THINKING.mac — Motor de razonamiento estructurado para Poli\n; Schema ^THINKING: sesiones de razonamiento trazables\n;\n; Licencia: MIT (Poli Core)\n; (c) 2026 Cadences Lab / Gonzalo Monzón\n;\n; Dependencias: UTILS.mac, MEMORY.mac\n;\n; #PublicApi\n\nTHINKING(session,action,metadata) ; Rutina principal — entry point\n  ; Crea un paso de razonamiento en ^THINKING\n  ; Input: session (string), action (deduce|search|decide|eval|abduce), metadata (array por referencia)\n  ; Output: step (integer) — número de paso creado\n  ;\n  ; metadata("type")      = deductive|inductive|abductive|analogical|causal|eval\n  ; metadata("agent")     = poli|zalo|lisa|tom|angi|hermes\n  ; metadata("input")     = texto del prompt o estado de entrada\n  ; metadata("output")    = resultado o conclusión\n  ; metadata("confidence") = 0.0–1.0\n  ; metadata("parent")    = step anterior (0 si raíz)\n  ; metadata("refs","decisions",n) = UUIDs de ^DECISIONS\n  ; metadata("refs","wiki",n)      = UUIDs de ^WIKI\n  ; metadata("refs","inputs",n)    = steps que alimentaron este\n  NEW step,ts\n  LOCK +^THINKING(session)\n  SET step=$ORDER(^THINKING(session,""),-1)+1\n  SET ^THINKING(session,step)=action\n  SET ^THINKING(session,step,"type")=$GET(metadata("type"))\n  SET ^THINKING(session,step,"agent")=$GET(metadata("agent"))\n  SET ^THINKING(session,step,"input")=$GET(metadata("input"))\n  SET ^THINKING(session,step,"output")=$GET(metadata("output"))\n  SET ^THINKING(session,step,"confidence")=$GET(metadata("confidence"))\n  SET ^THINKING(session,step,"parent")=$GET(metadata("parent"))\n  SET ts=$$NOW^UTILS()\n  SET ^THINKING(session,step,"timestamp")=ts\n  SET ^THINKING("idx","agent",$GET(metadata("agent")),ts,session,step)=""\n  SET ^THINKING("idx","type",action,session,step)=""\n  LOCK -^THINKING(session)\n  QUIT step\n\nGET ; Obtener un paso de razonamiento\n  ; Uso: DO GET^THINKING(.result, session, step)\n  ; Output: result("action"), result("type"), result("agent"), etc.\n  NEW i\n  SET result("action")=$GET(^THINKING(session,step))\n  SET result("type")=$GET(^THINKING(session,step,"type"))\n  SET result("status")=$GET(^THINKING(session,step,"status"),"completed")\n  SET result("agent")=$GET(^THINKING(session,step,"agent"))\n  SET result("input")=$GET(^THINKING(session,step,"input"))\n  SET result("output")=$GET(^THINKING(session,step,"output"))\n  SET result("confidence")=$GET(^THINKING(session,step,"confidence"))\n  SET result("timestamp")=$GET(^THINKING(session,step,"timestamp"))\n  SET result("parent")=$GET(^THINKING(session,step,"parent"),0)\n  SET i="" FOR  SET i=$ORDER(^THINKING(session,step,"refs","decisions",i)) QUIT:i=""  DO\n  . SET result("refs","decisions",i)=^THINKING(session,step,"refs","decisions",i)\n  SET i="" FOR  SET i=$ORDER(^THINKING(session,step,"refs","wiki",i)) QUIT:i=""  DO\n  . SET result("refs","wiki",i)=^THINKING(session,step,"refs","wiki",i)\n  SET i="" FOR  SET i=$ORDER(^THINKING(session,step,"refs","inputs",i)) QUIT:i=""  DO\n  . SET result("refs","inputs",i)=^THINKING(session,step,"refs","inputs",i)\n  QUIT\n\nCHAIN ; Obtener cadena completa de razonamiento\n  ; Uso: DO CHAIN^THINKING(.steps, session)\n  ; Output: steps(step, campo) para cada paso\n  NEW step\n  SET step="" FOR  SET step=$ORDER(^THINKING(session,step)) QUIT:step=""  DO\n  . NEW result\n  . DO GET^THINKING(.result,session,step)\n  . MERGE steps(step)=result\n  QUIT\n\nBYAGENT ; Buscar pasos por agente\n  ; Uso: DO BYAGENT^THINKING(.results, agent, fromts, count)\n  NEW ts,session,step,i\n  SET i=0\n  SET ts=fromts\n  FOR  SET ts=$ORDER(^THINKING("idx","agent",agent,ts)) QUIT:ts=""  DO  QUIT:i>=count\n  . SET session=$ORDER(^THINKING("idx","agent",agent,ts,""))\n  . SET step=$ORDER(^THINKING("idx","agent",agent,ts,session,""))\n  . SET i=i+1\n  . SET results(i,"session")=session\n  . SET results(i,"step")=step\n  . SET results(i,"timestamp")=ts\n  QUIT\n\nSTATUS ; Resumen de una sesión\n  ; Uso: DO STATUS^THINKING(.info, session)\n  NEW step,action\n  SET info("total")=0\n  SET info("actions")=""\n  SET step="" FOR  SET step=$ORDER(^THINKING(session,step)) QUIT:step=""  DO\n  . SET info("total")=info("total")+1\n  . SET action=$GET(^THINKING(session,step))\n  . SET $PIECE(info("actions"),",",action)=$GET($PIECE(info("actions"),",",action))+1\n  QUIT\n\nCLEANUP ; Limpiar sesiones antiguas\n  ; Uso: DO CLEANUP^THINKING(threshold)\n  ; Elimina sesiones anteriores a threshold (formato $H)\n  NEW session,step,ts\n  SET session="" FOR  SET session=$ORDER(^THINKING(session)) QUIT:session=""  DO\n  . SET step=$ORDER(^THINKING(session,""),-1)\n  . SET ts=$GET(^THINKING(session,step,"timestamp"))\n  . IF ts<threshold LOCK +^THINKING(session) KILL ^THINKING(session) LOCK -^THINKING(session)\n  QUIT\n
#[allow(unused_mut, unused_assignments, non_snake_case)]
pub fn THINKING(globals: &mut std::collections::BTreeMap<Vec<crate::Subscript>, crate::Value>>) -> Result<crate::Value, crate::VmError> {
    // Variables locales
    let mut step = crate::Value::Null;
    let mut step) = crate::Value::Null;
    let mut "type") = crate::Value::Null;
    let mut "agent") = crate::Value::Null;
    let mut "input") = crate::Value::Null;
    let mut "output") = crate::Value::Null;
    let mut "confidence") = crate::Value::Null;
    let mut "parent") = crate::Value::Null;
    let mut ts = crate::Value::Null;
    let mut "timestamp") = crate::Value::Null;
    let mut result("action") = crate::Value::Null;
    let mut result("type") = crate::Value::Null;
    let mut result("status") = crate::Value::Null;
    let mut result("agent") = crate::Value::Null;
    let mut result("input") = crate::Value::Null;
    let mut result("output") = crate::Value::Null;
    let mut result("confidence") = crate::Value::Null;
    let mut result("timestamp") = crate::Value::Null;
    let mut result("parent") = crate::Value::Null;
    let mut i = crate::Value::Null;
    let mut session = crate::Value::Null;
    let mut "session") = crate::Value::Null;
    let mut "step") = crate::Value::Null;
    let mut info("total") = crate::Value::Null;
    let mut info("actions") = crate::Value::Null;

    // Label: THINKING
    // (skipped New): step,ts
    // (skipped Lock): +^THINKING(session)
    // SET step=$ORDER(^THINKING(session,""),-1)+1
    step = crate::Value::Null /* unmapped: $ORDER(^THINKING(session */;
    // SET ^THINKING(session,step)=action
    step) = action.clone();
    // SET ^THINKING(session,step,"type")=$GET(metadata("type"))
    "type") = crate::Value::Null /* unmapped: $GET(metadata(\"type\")) */;
    // SET ^THINKING(session,step,"agent")=$GET(metadata("agent"))
    "agent") = crate::Value::Null /* unmapped: $GET(metadata(\"agent\")) */;
    // SET ^THINKING(session,step,"input")=$GET(metadata("input"))
    "input") = crate::Value::Null /* unmapped: $GET(metadata(\"input\")) */;
    // SET ^THINKING(session,step,"output")=$GET(metadata("output"))
    "output") = crate::Value::Null /* unmapped: $GET(metadata(\"output\")) */;
    // SET ^THINKING(session,step,"confidence")=$GET(metadata("confidence"))
    "confidence") = crate::Value::Null /* unmapped: $GET(metadata(\"confidence\")) */;
    // SET ^THINKING(session,step,"parent")=$GET(metadata("parent"))
    "parent") = crate::Value::Null /* unmapped: $GET(metadata(\"parent\")) */;
    // SET ts=$$NOW^UTILS()
    ts = crate::Value::Null /* unmapped: $$NOW^UTILS() */;
    // SET ^THINKING(session,step,"timestamp")=ts
    "timestamp") = ts.clone();
    // SET ^THINKING("idx","agent",$GET(metadata("agent")),ts,session,step)=""
    step) = crate::Value::String("".to_string());
    // SET ^THINKING("idx","type",action,session,step)=""
    step) = crate::Value::String("".to_string());
    // (skipped Lock): -^THINKING(session)
    break;
    // Label: GET
    // (skipped New): i
    // SET result("action")=$GET(^THINKING(session,step))
    result("action") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("type")=$GET(^THINKING(session,step,"type"))
    result("type") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("status")=$GET(^THINKING(session,step,"status"),"completed")
    result("status") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("agent")=$GET(^THINKING(session,step,"agent"))
    result("agent") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("input")=$GET(^THINKING(session,step,"input"))
    result("input") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("output")=$GET(^THINKING(session,step,"output"))
    result("output") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("confidence")=$GET(^THINKING(session,step,"confidence"))
    result("confidence") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("timestamp")=$GET(^THINKING(session,step,"timestamp"))
    result("timestamp") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET result("parent")=$GET(^THINKING(session,step,"parent"),0)
    result("parent") = crate::Value::Null /* unmapped: $GET(^THINKING(session */;
    // SET i=""
    i = crate::Value::String("".to_string());
    // FOR SET i=$ORDER(^THINKING(session,step,"refs","decisions",i)) QUIT:i=""  DO
. SET result("refs","decisions",i)=^THINKING(session,step,"refs","decisions",i):1
    for SET i_iter in $ORDER(^THINKING(session,step,"refs","decisions",i)) QUITf64 as i64..=i=""  DO
. SET result("refs","decisions",i)=^THINKING(session,step,"refs","decisions",i)f64 as i64 {
        let SET i = crate::Value::Number(SET i_iter as f64);
        // FOR body (todo en una línea)
        i = crate::Value::String("".to_string());
        // (not in body): For SET i=$ORDER(^THINKING(session,step,"refs","wiki",i)) QUIT:i=""  DO
        . SET result("refs","wiki",i)=^THINKING(session,step,"refs","wiki",i)
        i = crate::Value::String("".to_string());
        // (not in body): For SET i=$ORDER(^THINKING(session,step,"refs","inputs",i)) QUIT:i=""  DO
        . SET result("refs","inputs",i)=^THINKING(session,step,"refs","inputs",i)
        // (not in body): Quit
        // (not in body): Label CHAIN
        // (not in body): New step
        step = crate::Value::String("".to_string());
        // (not in body): For SET step=$ORDER(^THINKING(session,step)) QUIT:step=""  DO
        . NEW result
        . DO GET^THINKING(.result,session,step)
        . MERGE steps(step)=result
        // (not in body): Quit
        // (not in body): Label BYAGENT
        // (not in body): New ts,session,step,i
        i = crate::Value::Number(0f64);
        ts = fromts.clone();
        // (not in body): For SET ts=$ORDER(^THINKING("idx","agent",agent,ts)) QUIT:ts=""  DO  QUIT:i>=count
        session = crate::Value::Null /* unmapped: $ORDER(^THINKING(\"idx\" */;
        step = crate::Value::Null /* unmapped: $ORDER(^THINKING(\"idx\" */;
        i = crate::Value::Number(i.clone().as_number() + crate::Value::Number(1f64).as_number());
        "session") = session.clone();
        "step") = step.clone();
        "timestamp") = ts.clone();
        // (not in body): Quit
        // (not in body): Label STATUS
        // (not in body): New step,action
        info("total") = crate::Value::Number(0f64);
        info("actions") = crate::Value::String("".to_string());
        step = crate::Value::String("".to_string());
        // (not in body): For SET step=$ORDER(^THINKING(session,step)) QUIT:step=""  DO
        . SET info("total")=info("total")+1
        . SET action=$GET(^THINKING(session,step))
        . SET $PIECE(info("actions"),",",action)=$GET($PIECE(info("actions"),",",action))+1
        // (not in body): Quit
        // (not in body): Label CLEANUP
        // (not in body): New session,step,ts
        session = crate::Value::String("".to_string());
        // (not in body): For SET session=$ORDER(^THINKING(session)) QUIT:session=""  DO
        . SET step=$ORDER(^THINKING(session,""),-1)
        . SET ts=$GET(^THINKING(session,step,"timestamp"))
        . IF ts<threshold LOCK +^THINKING(session) KILL ^THINKING(session) LOCK -^THINKING(session)
        // (not in body): Quit
    }
    Ok(crate::Value::Null)
}
