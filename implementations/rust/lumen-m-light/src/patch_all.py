#!/usr/bin/env python3
"""Apply all MVM parser fixes atomically."""
import re

VM_RS = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\vm.rs'

with open(VM_RS, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: split_whitespace → smart space split in exec_do (already done, just re-apply)
old1 = 'let target = argument.split_whitespace().next().unwrap_or_default();'
new1 = '''// find first space outside parens/quotes (split_whitespace() rompe con espacios en strings)
        let target = {
            let mut depth = 0i32;
            let mut quoted = false;
            let mut split_at = argument.len();
            for (j, c) in argument.char_indices() {
                match c {
                    '\"' => quoted = !quoted,
                    '(' | '{' if !quoted => depth += 1,
                    ')' | '}' if !quoted => depth -= 1,
                    ' ' if depth == 0 && !quoted => { split_at = j; break; }
                    _ => {}
                }
            }
            &argument[..split_at]
        };'''

assert old1 in content, 'Fix 1: pattern not found'
content = content.replace(old1, new1, 1)
print('✅ Fix 1: smart space split')

# Fix 2: Add [ to find_comparison
old2 = 'for &(pattern, op) in &[(">=", ">="), ("<=", "<="), ("'=\"", "'=\""), ("!=", "!="), ("=", "="), (">", ">"), ("<", "<")]'
new2 = 'for &(pattern, op) in &[(">=", ">="), ("<=", "<="), ("'=\"", "'=\""), ("!=", "!="), ("[", "["), ("=", "="), (">", ">"), ("<", "<")]'
assert old2 in content, 'Fix 2: pattern not found'
content = content.replace(old2, new2, 1)
print('✅ Fix 2: [ operator in comparisons')

# Fix 3: Add ! and & to split_arithmetic operators
old3 = "op @ (b'+' | b'-' | b'*' | b'/' | b'\\\\' | b'#' | b'_')"
new3 = "op @ (b'+' | b'-' | b'*' | b'/' | b'\\\\' | b'#' | b'_' | b'!' | b'&')"
assert old3 in content, 'Fix 3: pattern not found'
content = content.replace(old3, new3, 1)
print('✅ Fix 3: ! and & operators')

# Fix 4: Add ! and & to apply_operator
old4 = '''fn apply_operator(
    left: Value,
    right: Value,
    operator: char,
    line: usize,
) -> Result<Value, VmError> {
    if operator == '_' {'''
new4 = '''fn apply_operator(
    left: Value,
    right: Value,
    operator: char,
    line: usize,
) -> Result<Value, VmError> {
    // Logical operators: ! (OR), & (AND) — work on truthiness
    if operator == '!' {
        let l = left.truthy();
        let r = right.truthy();
        return Ok(Value::Bool(l || r));
    }
    if operator == '&' {
        let l = left.truthy();
        let r = right.truthy();
        return Ok(Value::Bool(l && r));
    }
    if operator == '_' {'''
assert old4 in content, 'Fix 4: pattern not found'
content = content.replace(old4, new4, 1)
print('✅ Fix 4: ! and & apply_operator')

# Fix 5: Add [ handler in compare_values
old5 = '''        "<=" => !ordering.is_gt(),
        _ => false,
    }
}'''
new5 = '''        "<=" => !ordering.is_gt(),
        "[" => left.as_string().contains(&right.as_string()),
        _ => false,
    }
}'''
assert old5 in content, 'Fix 5: pattern not found'
content = content.replace(old5, new5, 1)
print('✅ Fix 5: [ handler in compare_values')

with open(VM_RS, 'w', encoding='utf-8') as f:
    f.write(content)

print('\n🎉 All fixes applied!')
