.PHONY: all clean

all: libv1.so libv2.so

# v1 (old): no version script — symbols are unversioned (bare foo, bar)
libv1.so: bad.c
	gcc -shared -fPIC -g -o libv1.so bad.c

# v2 (new): uses version script — symbols are versioned (foo@@LIBFOO_1.0)
# COMPATIBLE: ld.so soft-matches versioned exports to unversioned references
libv2.so: good.c libfoo.map
	gcc -shared -fPIC -g -Wl,--version-script=libfoo.map -o libv2.so good.c

clean:
	rm -f libv1.so libv2.so
