/* Process-name shim: run a Python interpreter in-process under another name.
 *
 * macOS names a process after its executable file. Homebrew's framework Python
 * re-execs into Python.app/Contents/MacOS/Python, and uv's interpreters are a
 * file called python3.X, so every daemon shows as "Python" in Activity Monitor
 * and Stats. A copy of this binary named after the daemon fixes that.
 *
 * The shim loads libpython with dlopen and sets config.executable to TARGET,
 * so sys.executable, sys.prefix and sys.path are the same as when TARGET runs
 * (venv detection included). If libpython is gone (a Python upgrade removed
 * it), the shim execs TARGET, so the daemon still starts, under the old name.
 *
 * Build with bin/procname, which supplies LIBPYTHON, TARGET and the headers
 * of the interpreter that TARGET runs.
 */
#include <Python.h>
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>

#if !defined(LIBPYTHON) || !defined(TARGET)
#error "build with -DLIBPYTHON=... -DTARGET=..."
#endif

static void fallback(int argc, char *argv[], const char *why) {
    fprintf(stderr, "procname: %s, running %s\n", why, TARGET);
    (void)argc;
    argv[0] = (char *)TARGET;
    execv(TARGET, argv);
    perror("procname: execv " TARGET);
    _exit(127);
}

#define SYM(var, name)                                         \
    var = dlsym(lib, name);                                    \
    if (!var) fallback(argc, argv, "missing symbol " name)

int main(int argc, char *argv[]) {
    void *lib = dlopen(LIBPYTHON, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) fallback(argc, argv, dlerror());

    void (*init_config)(PyConfig *);
    PyStatus (*set_bytes)(PyConfig *, wchar_t **, const char *);
    PyStatus (*set_argv)(PyConfig *, Py_ssize_t, char *const *);
    PyStatus (*init_from)(const PyConfig *);
    int (*is_exception)(PyStatus);
    void (*exit_status)(PyStatus);
    void (*clear)(PyConfig *);
    int (*run_main)(void);
    SYM(init_config, "PyConfig_InitPythonConfig");
    SYM(set_bytes, "PyConfig_SetBytesString");
    SYM(set_argv, "PyConfig_SetBytesArgv");
    SYM(init_from, "Py_InitializeFromConfig");
    SYM(is_exception, "PyStatus_Exception");
    SYM(exit_status, "Py_ExitStatusException");
    SYM(clear, "PyConfig_Clear");
    SYM(run_main, "Py_RunMain");

    PyConfig config;
    PyStatus st;
    init_config(&config);
    st = set_bytes(&config, &config.executable, TARGET);
    if (is_exception(st)) goto fail;
    st = set_bytes(&config, &config.program_name, TARGET);
    if (is_exception(st)) goto fail;
    st = set_argv(&config, argc, argv);
    if (is_exception(st)) goto fail;
    st = init_from(&config);
    if (is_exception(st)) goto fail;
    clear(&config);
    return run_main();

fail:
    clear(&config);
    exit_status(st);
    return 1;
}
