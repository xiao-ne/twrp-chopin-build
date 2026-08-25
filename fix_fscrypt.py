import re

for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    try:
        with open(fname) as f:
            content = f.read()
    except FileNotFoundError:
        continue
    
    # Find the fscrypt block: from fscrypt_policy_get_struct to the matching closing brace
    # Use a simpler approach: just comment out problematic lines
    
    # Comment out lines with incompatible function calls
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if any(fn in line for fn in [
            'fscrypt_policy_get_struct', 'fscrypt_policy_size',
            'get_policy_size', 'get_policy_descriptor',
            'lookup_ref_key(t->th_buf.fep', 'get_policy(',
            'fscrypt_policy *fep', 'struct fscrypt_policy_v1'
        ]):
            new_lines.append('/* DISABLED: ' + line.strip() + ' */')
        else:
            new_lines.append(line)
    
    with open(fname, 'w') as f:
        f.write('\n'.join(new_lines))
    print(f'Patched {fname}')

# Fix libtar.h
try:
    with open('bootable/recovery/libtar/libtar.h') as f:
        content = f.read()
    content = content.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open('bootable/recovery/libtar/libtar.h', 'w') as f:
        f.write(content)
    print('Patched libtar.h')
except:
    pass
