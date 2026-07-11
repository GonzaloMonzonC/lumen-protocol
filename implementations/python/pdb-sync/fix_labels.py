"""Fix compile step for labels with parens like SCAN(ns)."""
lines = open('m_stackvm.py').readlines()
new = []
for line in lines:
    if 'first_word == first_word.upper()' in line:
        new.append(line)
        new.append('                # Labels con args: SCAN(ns), SCAN2(ns)\n')
        new.append('                if "(" in first_word:\n')
        new.append('                    first_word = first_word.split("(")[0]\n')
    elif 'if first_word not in cmd_tokens:' in line:
        new.append(line.rstrip() + ' and "(" not in first_word\n')
    else:
        new.append(line)
open('m_stackvm.py', 'w').writelines(new)
print('Fixed labels')
