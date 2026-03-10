.PHONY: all clean

all: libv1.so libv2.so

# v1 (old): uses version script — symbols are versioned (foo@@LIBFOO_1.0)
libv1.so: good.c libfoo.map
	gcc -shared -fPIC -g -Wl,--version-script=libfoo.map -o libv1.so good.c

# v2 (new): no version script — symbols are unversioned (bare foo)
# BREAKING: any binary linked against foo@@LIBFOO_1.0 gets a hard lookup error
libv2.so: bad.c
	gcc -shared -fPIC -g -o libv2.so bad.c

clean:
	rm -f libv1.so libv2.so
