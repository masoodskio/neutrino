# Temporary diagnostic build: only this shim enables DEBUG.
IOP_CFLAGS += -DDEBUG -I../smap/include -I../fakemod/src

IOP_OBJS = trace_main.o ioplib.o imports.o
IOP_OBJS_DIR = obj/
IOP_BIN = smap_inet.irx

include ../Rules.make

obj/trace_main.o: src/main.c src/netdev.h
