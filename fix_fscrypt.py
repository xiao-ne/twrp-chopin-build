#!/usr/bin/env python3
"""Aggressively fix fscrypt by commenting out problematic blocks."""
import os

for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    if not os.path.exists(fname):
        print(f'Skip {fname}')
        continue
    with open(fname) as f:
        lines = f.readlines()
    
    # Keywords that indicate fscrypt-related problematic code
    keywords = [
        'fscrypt_policy_get_struct', 'fscrypt_policy_size',
        'get_policy_size', 'get_policy_descriptor',
        'lookup_ref_key(t->th_buf.fep',
        't->th_buf.fep',
    ]
    
    result = []
    in_skip = False
    brace_depth = 0
    
    for i, line in enumerate(lines):
        if in_skip:
            brace_depth += line.count('{') - line.count('}')
            if brace_depth <= 0:
                in_skip = False
                result.append('#endif /* fscrypt disabled */\n')
            continue
        
        # Check if this line starts a problematic block
        if any(kw in line for kw in keywords):
            in_skip = True
            brace_depth = line.count('{') - line.count('}')
            result.append('#if 0 /* fscrypt disabled for compatibility */\n')
            result.append(line)
            if brace_depth <= 0:
                in_skip = False
                result.append('#endif /* fscrypt disabled */\n')
            continue
        
        result.append(line)
    
    with open(fname, 'w') as f:
        f.writelines(result)
    print(f'Fixed {fname}')

# Fix libtar.h
fname = 'bootable/recovery/libtar/libtar.h'
if os.path.exists(fname):
    with open(fname) as f:
        c = f.read()
    c = c.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open(fname, 'w') as f:
        f.write(c)
    print(f'Fixed {fname}')
