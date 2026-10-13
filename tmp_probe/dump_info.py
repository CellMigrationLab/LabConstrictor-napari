import sys
from minidump.minidumpfile import MinidumpFile

mf = MinidumpFile.parse(sys.argv[1])
print("DUMP", sys.argv[1])
for rec in mf.exception.exception_records:
    r = rec.ExceptionRecord
    addr = r.ExceptionAddress
    print("  thread", rec.ThreadId, "code", hex(r.ExceptionCode), "address", hex(addr), "params", [hex(p) for p in r.ExceptionInformation[:3]])
    for m in mf.modules.modules:
        if m.baseaddress <= addr < m.baseaddress + m.size:
            print("  faulting module:", m.name, "offset", hex(addr - m.baseaddress))
print("  threads:", [t.ThreadId for t in mf.threads.threads])
print("  modules containing 'mesa|gallium|opengl|llvm|Qt6|shiboken|PySide':")
for m in mf.modules.modules:
    n = m.name.lower()
    if any(k in n for k in ("gallium", "opengl", "libglapi", "qt6", "shiboken", "pyside")):
        print("    ", m.name)
