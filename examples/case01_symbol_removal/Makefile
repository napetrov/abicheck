.PHONY: all clean test-break

CC ?= gcc

all: libv1.so libv2.so app_v1

libv1.so: v1.c
	$(CC) -shared -fPIC -g -o libv1.so v1.c

libv2.so: v2.c
	$(CC) -shared -fPIC -g -o libv2.so v2.c

app_v1: app.c libv1.so
	$(CC) -g app.c -L. -lv1 -Wl,-rpath,. -o app_v1

test-break: all
	cp libv1.so libv1.so.bak
	cp libv2.so libv1.so
	./app_v1; ret=$$?; mv libv1.so.bak libv1.so; echo "EXIT:$$ret"; exit $$ret

clean:
	rm -f libv1.so libv2.so app_v1 libv1.so.bak
