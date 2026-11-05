# SPDX-License-Identifier: GPL-2.0-or-later
"""What one source file defines, refers to and says, read with tree-sitter.

Everything here goes by name and by the shape of a string, so it's approximate: two things with one name are
mixed up, what a macro or generated code hides is missed, and a path that's put together at run time isn't seen.
The result depends only on the file's content and EXTRACTOR, so a file that hasn't changed is never parsed again.
A query's captures come in no useful order, and not the same one each run, so everything is sorted before it's used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import tree_sitter
import tree_sitter_bash
import tree_sitter_c
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_rust

EXTRACTOR = 1  # raise it when what's extracted changes, and every file is read again
MAX_LINES_KEPT = 12  # of one name in one file: the count stays exact

LANGUAGES = {"c": "C", "python": "Python", "javascript": "JavaScript", "shell": "Shell", "rust": "Rust"}
_BY_SUFFIX = {".c": "c", ".h": "c", ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
              ".sh": "shell", ".bash": "shell", ".ash": "shell", ".rs": "rust"}
_BY_NAME = {"APKBUILD": "shell"}
_SHEBANG = re.compile(rb"#!\s*(?:/usr)?(?:/local)?/s?bin/(?:env\s+(?:-\S+\s+)*)?(\S+)")
_BY_INTERPRETER = {"sh": "shell", "bash": "shell", "ash": "shell", "dash": "shell", "openrc-run": "shell", "node": "javascript"}


def suffix(path: str) -> str:
    """The file's last suffix, or what the file is called if it has none: how the map counts what it doesn't cover."""
    name = path.rsplit("/", 1)[-1]
    head, dot, tail = name.rpartition(".")
    return f".{tail.lower()}" if dot and head else "(no suffix)"


def language_of(path: str, head: bytes | None = None) -> str | None:
    """By name, then by the first line if the name says nothing. head is None when that isn't known yet."""
    name = path.rsplit("/", 1)[-1]
    found = _BY_NAME.get(name) or _BY_SUFFIX.get(suffix(path))
    if found or head is None:
        return found
    shebang = _SHEBANG.match(head)
    if not shebang:
        return None
    interpreter = shebang.group(1).decode(errors="replace")
    return "python" if interpreter.startswith("python") else _BY_INTERPRETER.get(interpreter)


def needs_a_look(path: str) -> bool:
    """A file with no suffix can be a script, and only its first line says."""
    return suffix(path) == "(no suffix)" or path.rsplit("/", 1)[-1].rsplit(".", 1)[-1] in ("post-install", "post-upgrade", "pre-install", "pre-deinstall", "post-deinstall", "pre-upgrade")


# --- the shape of a string -----------------------------------------------------------
_ROOTS = "dev|run|sys|proc|etc|var|tmp|usr|opt|lib|lib64|mnt|boot|media|srv|sbin|bin|data|home|root"
_PATH = re.compile(rf"/(?:{_ROOTS})(?:/[^\s\"'<>|;&()]*)?")
_NOISE = {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/tty", "/bin/sh", "/bin/bash", "/usr/bin/env",
          "/tmp", "/tmp/", "/usr", "/etc", "/etc/", "/usr/", "/dev", "/dev/", "/proc", "/sys", "/run", "/var", "/bin", "/sbin", "/lib"}
_ENV = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
_KEY = re.compile(r"@?([a-z][a-z0-9_.-]{2,}=)\S*")  # eink.conf's own lines start with @
_FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:conf|cfg|ini|toml|ctl|sock|socket|fifo|pid|lock)")
_PACKAGE = re.compile(r"[a-z0-9][a-z0-9+._-]*")
MAX_STRING = 300


def shape_of(text: str) -> tuple[str, str] | None:
    """(what it looks like, the part to compare), or None for a string that's none of these, as most are."""
    if not text or len(text) > MAX_STRING or text in _NOISE:
        return None
    if _PATH.fullmatch(text):
        return ("device" if text.startswith("/dev/") else "path"), text
    if _ENV.fullmatch(text):
        return "key", text
    key = _KEY.fullmatch(text)
    if key:
        return "key", key.group(1)
    if _FILE.fullmatch(text):
        return "file", text
    return None


# --- what a call does with a file ----------------------------------------------------
# A hint from the call's name; flags in its arguments can settle what open() left open.
_ACCESS = {"fopen": "open", "open": "open", "open64": "open", "openat": "open", "os.open": "open", "creat": "write", "mkfifo": "create", "os.mkfifo": "create", "mknod": "create", "os.mknod": "create",
           "unlink": "remove", "remove": "remove", "os.remove": "remove", "os.unlink": "remove", "rm": "remove", "chmod": "permissions", "chown": "permissions", "os.chmod": "permissions", "os.chown": "permissions",
           "access": "check", "stat": "check", "lstat": "check", "os.stat": "check", "os.path.exists": "check", "read_text": "read", "read_bytes": "read", "write_text": "write", "write_bytes": "write",
           "readFile": "read", "readFileSync": "read", "writeFile": "write", "writeFileSync": "write", "appendFile": "write", "appendFileSync": "write", "createReadStream": "read", "createWriteStream": "write",
           "File::open": "read", "File::create": "write", "fs::read": "read", "fs::read_to_string": "read", "fs::write": "write", "std::fs::read": "read", "std::fs::read_to_string": "read", "std::fs::write": "write",
           "std::fs::File::open": "read", "std::fs::File::create": "write", "fs::File::open": "read", "fs::File::create": "write", "fs::remove_file": "remove", "std::fs::remove_file": "remove",
           "cat": "read", "tail": "read", "head": "read", "tee": "write", "touch": "create"}
# Only these mean a file whatever they're called on: x.remove() and x.open() usually don't.
_METHODS = {"read_text", "read_bytes", "write_text", "write_bytes", "readFile", "readFileSync", "writeFile", "writeFileSync", "appendFile", "appendFileSync", "createReadStream", "createWriteStream"}
MAX_ARGS_READ = 8  # for flags and a mode: they're never far along
_WRITES = re.compile(r"\bO_(?:WRONLY|APPEND|CREAT|TRUNC)\b|^[\"'](?:w|a|x)[bt+]*[\"']$")
_BOTH = re.compile(r"\bO_RDWR\b|^[\"'](?:r\+|w\+|a\+|r\+b|rb\+)[\"']$")
_READS = re.compile(r"\bO_RDONLY\b|^[\"'](?:r|rb|rt)[\"']$")


def _names_a_file(call: str | None) -> bool:
    return bool(call) and (call in _ACCESS or call.rsplit(".", 1)[-1] in _METHODS)


def _settled(call: str | None, args: list[str]) -> str | None:
    if call and call not in _ACCESS and call.rsplit(".", 1)[-1] in _METHODS:
        call = call.rsplit(".", 1)[-1]
    hint = _ACCESS.get(call) if call else None
    if hint != "open":
        return hint
    both = reads = writes = False
    for text in args:
        text = text.removeprefix("mode=").removeprefix("flags=")
        both = both or bool(_BOTH.search(text))
        writes = writes or bool(_WRITES.search(text))
        reads = reads or bool(_READS.search(text))
    if both or (reads and writes):
        return "read and write"
    if writes:
        return "write"
    return "read" if reads or call in ("open", "fopen") and len(args) <= 1 else "open"


@dataclass
class Facts:
    defs: list = field(default_factory=list)     # (name, kind, line, end line)
    refs: dict = field(default_factory=dict)     # name -> [count, [lines]]
    strings: list = field(default_factory=list)  # (value, shape, line, role, constant, function, call, access)
    flows: list = field(default_factory=list)    # (name, line, function, call, access): a name handed to something that touches a file
    errors: bool = False
    lines: int = 0

    def ref(self, name: str, line: int) -> None:
        row = self.refs.setdefault(name, [0, []])
        row[0] += 1
        row[1].append(line)

    def settle(self) -> "Facts":
        """The first lines of each name, not whichever came up first, and everything in file order."""
        for row in self.refs.values():
            row[1] = sorted(set(row[1]))[:MAX_LINES_KEPT]
        self.defs.sort(key=lambda d: (d[2], d[0], d[1]))
        self.strings.sort(key=lambda s: (s[2], s[0], s[3]))
        self.flows.sort(key=lambda f: (f[1], f[0]))
        return self


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def _line(node) -> int:
    return node.start_point[0] + 1


def _in_order(cursor, root) -> list:
    return sorted((n for nodes in cursor.captures(root).values() for n in nodes), key=lambda n: n.start_byte)


class _Language:
    """One grammar's queries. defs: capture names are the kind of definition."""
    defs = refs = locals = calls = strings = ""
    functions: tuple = ()
    call_nodes: tuple = ()
    _calls: dict = {}

    def __init__(self, grammar):
        self.language = tree_sitter.Language(grammar)
        self.parser = tree_sitter.Parser(self.language)
        make = lambda source: tree_sitter.QueryCursor(tree_sitter.Query(self.language, source)) if source else None
        self.q_defs, self.q_refs, self.q_locals, self.q_calls, self.q_strings = map(make, (self.defs, self.refs, self.locals, self.calls, self.strings))

    def function_name(self, node) -> str | None:
        name = node.child_by_field_name("name")
        return _text(name) if name else None

    def call_name(self, call) -> str | None:
        target = call.child_by_field_name("function")
        return _text(target).replace(" ", "") if target else None

    def call_args(self, call) -> list:
        args = call.child_by_field_name("arguments")
        return [a for a in args.children if a.is_named and a.type != "comment"] if args else []

    def constant(self, node) -> str | None:
        """The name a string is given where it's defined, or None if it's used in place."""
        return None

    def extra(self, root, source: bytes, facts: Facts) -> None:
        pass

    def string_value(self, node) -> str | None:
        return _text(node)

    def context(self, node) -> tuple[str | None, object]:
        """The function a node is in, and the nearest call around it."""
        function, call = None, None
        at = node.parent
        while at is not None:
            if call is None and at.type in self.call_nodes:
                call = at
            if at.type in self.functions:
                function = self.function_name(at)
                break
            at = at.parent
        return function, call

    def _call_facts(self, call) -> tuple[str | None, str | None]:
        """The call's name and what it does to a file. Once per call: one with thousands of arguments is asked once per argument."""
        known = self._calls.get(call.id)
        if known is None:
            known = self._calls[call.id] = self._work_out_call(call)
        return known

    def _work_out_call(self, call) -> tuple[str | None, str | None]:
        name = self.call_name(call)
        if not _names_a_file(name):  # most calls, and no need to read their arguments
            return name, None
        return name, _settled(name, [_text(a) for a in self.call_args(call)[:MAX_ARGS_READ]])

    def flow(self, node) -> tuple[str | None, str | None, str | None]:
        """Function, call, access."""
        function, call = self.context(node)
        if call is None:
            return function, None, None
        return (function, *self._call_facts(call))

    def _ref_nodes(self, root) -> list:
        return _in_order(self.q_refs, root)

    def facts(self, source: bytes) -> Facts:
        outer, self._calls = self._calls, {}  # a node's id means something only within its own tree
        try:
            return self._facts(source)
        finally:
            self._calls = outer

    def _facts(self, source: bytes) -> Facts:
        tree = self.parser.parse(source)
        root = tree.root_node
        facts = Facts(errors=root.has_error, lines=source.count(b"\n") + 1)
        at_def = set()
        for kind, nodes in self.q_defs.captures(root).items():
            for node in nodes:
                definition = self.definition(kind, node)
                if definition is None:
                    continue
                name, line, end = definition
                facts.defs.append((name, kind, line, end))
                at_def.add((name, line))
        defined = {d[0] for d in facts.defs}
        local = {_text(n) for nodes in self.q_locals.captures(root).values() for n in nodes} - defined if self.q_locals else set()
        for node in self._ref_nodes(root):
            name, line = _text(node), _line(node)
            if name and name not in local and (name, line) not in at_def:
                facts.ref(name, line)
        if self.q_calls:
            for node in _in_order(self.q_calls, root):
                if _names_a_file(_text(node).replace(" ", "")):
                    self._flows_of_call(node, facts)
        for node in _in_order(self.q_strings, root):
            value = self.string_value(node)
            if value:
                self._string(node, value, facts)
        self.extra(root, source, facts)
        return facts

    def definition(self, kind: str, node) -> tuple[str, int, int] | None:
        """node is the name; its parent is the definition, usually."""
        return _text(node), _line(node), (node.parent.end_point[0] + 1 if node.parent else _line(node))

    def _flows_of_call(self, callee, facts: Facts) -> None:
        call = callee
        while call is not None and call.type not in self.call_nodes:
            call = call.parent
        if call is None:
            return
        function, name, access = self.flow(callee)
        if access is None:
            return
        for arg in self.call_args(call):
            if arg.type in self.name_args:
                facts.flows.append((_text(arg), _line(arg), function, name, access))

    name_args: tuple = ("identifier",)

    def _string(self, node, value: str, facts: Facts) -> None:
        shape = shape_of(value)
        if shape is None:
            return
        constant = self.constant(node)
        function, call, access = self.flow(node)
        facts.strings.append((shape[1], shape[0], _line(node), "define" if constant else "use", constant, function, call, access))


class _C(_Language):
    functions = ("function_definition",)
    call_nodes = ("call_expression",)
    defs = """
        (function_definition) @function
        (struct_specifier name: (type_identifier) @struct body: (_))
        (union_specifier name: (type_identifier) @union body: (_))
        (enum_specifier name: (type_identifier) @enum body: (_))
        (type_definition declarator: (type_identifier) @typedef)
        (preproc_def name: (identifier) @macro)
        (preproc_function_def name: (identifier) @macro)
        (enumerator name: (identifier) @enumerator)
        (translation_unit (declaration) @variable)
    """
    refs = """
        (identifier) @name
        (type_identifier) @name
        (call_expression function: (field_expression field: (field_identifier) @name))
    """
    locals = """
        (parameter_declaration declarator: (identifier) @local)
        (pointer_declarator declarator: (identifier) @local)
        (array_declarator declarator: (identifier) @local)
        (compound_statement (declaration declarator: (identifier) @local))
        (compound_statement (declaration declarator: (init_declarator declarator: (identifier) @local)))
        (for_statement initializer: (declaration declarator: (init_declarator declarator: (identifier) @local)))
    """
    calls = "(call_expression function: (identifier) @call)"
    strings = "(string_literal) @string"
    _macro_word = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
    _macro_string = re.compile(rb'"((?:[^"\\\n]|\\.)*)"')
    _keywords = {"if", "else", "for", "while", "do", "switch", "case", "return", "sizeof", "goto", "break", "continue", "default"}  # what macros can make the grammar take for names

    def function_name(self, node) -> str | None:
        return _declared(node.child_by_field_name("declarator"))

    def _ref_nodes(self, root):
        return [n for n in super()._ref_nodes(root) if n.text.decode("utf-8", "replace") not in self._keywords]

    def definition(self, kind, node):
        found = self._c_definition(kind, node)
        return None if found is None or found[0] in self._keywords else found

    def _c_definition(self, kind, node):
        if kind == "function":
            name = _declared(node.child_by_field_name("declarator"))
            return (name, _line(node), node.end_point[0] + 1) if name else None
        if kind == "variable":
            if any(c.type == "storage_class_specifier" and c.text == b"extern" for c in node.children):
                return None
            declarator = node.child_by_field_name("declarator")
            if declarator is None or _is_prototype(declarator):
                return None
            name = _declared(declarator)
            return (name, _line(node), node.end_point[0] + 1) if name else None
        return super().definition(kind, node)

    def string_value(self, node):
        parts = [c for c in node.children if c.type not in ('"', "string_literal")]
        if not parts or any(c.type != "string_content" for c in parts):
            return None
        return _text(parts[0])

    def constant(self, node):
        at = node.parent
        if at is not None and at.type == "init_declarator":
            declaration = at.parent
            if declaration is not None and declaration.parent is not None and (declaration.parent.type == "translation_unit" or _text(declaration).startswith(("static", "const"))):
                return _declared(at.child_by_field_name("declarator"))
        return None

    def extra(self, root, source, facts):
        """A preprocessor body isn't parsed: its words count as uses, and a macro that is a string defines that string."""
        for node in _preproc_args(root):
            body = node.text
            line = _line(node)
            for word in self._macro_word.finditer(self._macro_string.sub(b" ", body)):
                if word.group().decode() not in self._keywords:
                    facts.ref(word.group().decode(), line)
            parent = node.parent
            string = self._macro_string.fullmatch(body.strip())
            if string and parent is not None and parent.type == "preproc_def":
                shape = shape_of(string.group(1).decode("utf-8", "replace"))
                name = parent.child_by_field_name("name")
                if shape and name is not None:
                    facts.strings.append((shape[1], shape[0], line, "define", _text(name), None, None, None))


def _preproc_args(root) -> list:
    return _in_order(_PREPROC_CURSOR, root)


def _declared(node) -> str | None:
    """The name inside a C declarator, however many pointers and parentheses are around it."""
    while node is not None:
        if node.type in ("identifier", "type_identifier", "field_identifier"):
            return _text(node)
        following = node.child_by_field_name("declarator")
        if following is None:
            following = next((c for c in node.children if c.type in ("identifier", "parenthesized_declarator", "pointer_declarator")), None)
        node = following
    return None


def _is_prototype(node) -> bool:
    while node is not None:
        if node.type == "function_declarator":
            return True
        if node.type == "init_declarator":
            return False
        node = node.child_by_field_name("declarator")
    return False


class _Python(_Language):
    functions = ("function_definition",)
    call_nodes = ("call",)
    defs = """
        (function_definition name: (identifier) @function)
        (class_definition name: (identifier) @class)
        (module (expression_statement (assignment left: (identifier) @variable)))
    """
    refs = "(identifier) @name"
    locals = """
        (parameters (identifier) @local)
        (default_parameter name: (identifier) @local)
        (typed_parameter (identifier) @local)
        (typed_default_parameter name: (identifier) @local)
        (keyword_argument name: (identifier) @local)
        (for_statement left: (identifier) @local)
        (function_definition body: (block (expression_statement (assignment left: (identifier) @local))))
    """
    calls = """
        (call function: (identifier) @call)
        (call function: (attribute) @call)
    """
    strings = "(string) @string"

    def string_value(self, node):
        parts = [c for c in node.children if c.type not in ("string_start", "string_end")]
        if not parts or any(c.type != "string_content" for c in parts):
            return None
        return _text(parts[0])

    def constant(self, node):
        """X = "…", or X = Path("…"), outside a function or in a class."""
        at = node.parent
        while at is not None and at.type in ("call", "argument_list", "binary_operator", "parenthesized_expression", "attribute"):
            at = at.parent
        if at is None or at.type != "assignment":
            return None
        left = at.child_by_field_name("left")
        owner = at.parent.parent if at.parent is not None else None
        if left is None or left.type != "identifier" or owner is None:
            return None
        return _text(left) if owner.type in ("module",) or (owner.parent is not None and owner.parent.type == "class_definition") else None

    def _work_out_call(self, call):
        # Path("…").write_text(…): what the path is used for is the call on it.
        outer = call.parent
        if outer is not None and outer.type == "attribute" and outer.parent is not None and outer.parent.type == "call":
            attribute = outer.child_by_field_name("attribute")
            if attribute is not None:
                name = _text(attribute)
                return name, _settled(name, [_text(a) for a in self.call_args(outer.parent)[:MAX_ARGS_READ]])
        return super()._work_out_call(call)


class _JavaScript(_Language):
    functions = ("function_declaration", "function_expression", "arrow_function", "method_definition", "generator_function_declaration")
    call_nodes = ("call_expression", "new_expression")
    defs = """
        (function_declaration name: (identifier) @function)
        (generator_function_declaration name: (identifier) @function)
        (class_declaration name: (identifier) @class)
        (method_definition name: (property_identifier) @method)
        (variable_declarator name: (identifier) @function value: [(function_expression) (arrow_function)])
        (program (lexical_declaration (variable_declarator name: (identifier) @variable)))
        (program (variable_declaration (variable_declarator name: (identifier) @variable)))
        (program (export_statement (lexical_declaration (variable_declarator name: (identifier) @variable))))
    """
    refs = """
        (identifier) @name
        (call_expression function: (member_expression property: (property_identifier) @name))
    """
    locals = """
        (formal_parameters (identifier) @local)
        (formal_parameters (assignment_pattern left: (identifier) @local))
        (arrow_function parameter: (identifier) @local)
        (statement_block (lexical_declaration (variable_declarator name: (identifier) @local)))
        (statement_block (variable_declaration (variable_declarator name: (identifier) @local)))
    """
    calls = """
        (call_expression function: (identifier) @call)
        (call_expression function: (member_expression) @call)
    """
    strings = "(string) @string"

    def string_value(self, node):
        parts = [c for c in node.children if c.type == "string_fragment"]
        return _text(parts[0]) if len(parts) == 1 and all(c.type != "escape_sequence" for c in node.children) else None

    def constant(self, node):
        at = node.parent
        if at is None or at.type != "variable_declarator":
            return None
        name = at.child_by_field_name("name")
        return _text(name) if name is not None and name.type == "identifier" else None


class _Rust(_Language):
    functions = ("function_item", "closure_expression")
    call_nodes = ("call_expression",)
    defs = """
        (function_item name: (identifier) @function)
        (function_signature_item name: (identifier) @function)
        (struct_item name: (type_identifier) @struct)
        (enum_item name: (type_identifier) @enum)
        (union_item name: (type_identifier) @union)
        (trait_item name: (type_identifier) @trait)
        (type_item name: (type_identifier) @type)
        (const_item name: (identifier) @constant)
        (static_item name: (identifier) @static)
        (mod_item name: (identifier) @module body: (_))
        (macro_definition name: (identifier) @macro)
        (enum_variant name: (identifier) @variant)
    """
    refs = """
        (identifier) @name
        (type_identifier) @name
        (call_expression function: (field_expression field: (field_identifier) @name))
    """
    locals = """
        (let_declaration pattern: (identifier) @local)
        (parameter pattern: (identifier) @local)
        (closure_parameters (identifier) @local)
        (for_expression pattern: (identifier) @local)
    """
    calls = """
        (call_expression function: (identifier) @call)
        (call_expression function: (scoped_identifier) @call)
    """
    strings = """
        (string_literal) @string
        (raw_string_literal) @string
    """

    def string_value(self, node):
        parts = [c for c in node.children if c.type == "string_content"]
        return _text(parts[0]) if len(parts) == 1 and all(c.type != "escape_sequence" for c in node.children) else None

    def constant(self, node):
        at = node.parent
        while at is not None and at.type in ("reference_expression", "call_expression", "arguments"):
            at = at.parent
        if at is not None and at.type in ("const_item", "static_item"):
            name = at.child_by_field_name("name")
            return _text(name) if name is not None else None
        return None


_PACKAGE_MANAGERS = {"apk": ("add", "del"), "apt-get": ("install", "remove"), "apt": ("install", "remove"), "pacman": ("-S", "-Sy", "-Syu", "-R")}
_PACKAGE_FIELDS = {"depends", "makedepends", "checkdepends", "depends_dev", "makedepends_build", "makedepends_host"}
_RUNS_A_SCRIPT = {"sh", "bash", "ash", "dash", "ssh", "docker", "chroot", "adb", "su", "podman"}
MAX_NESTED = 3


class _Shell(_Language):
    functions = ("function_definition",)
    call_nodes = ("command",)
    defs = """
        (function_definition name: (word) @function)
        (program (variable_assignment name: (variable_name) @variable))
    """
    refs = """
        (command_name (word) @name)
        (simple_expansion (variable_name) @name)
        (expansion (variable_name) @name)
    """
    locals = "(declaration_command (variable_assignment name: (variable_name) @local))"
    calls = "(command_name) @call"
    strings = """
        (word) @string
        (raw_string) @string
        (string) @string
    """
    name_args = ()

    def __init__(self, grammar):
        super().__init__(grammar)
        self.q_redirects = tree_sitter.QueryCursor(tree_sitter.Query(self.language, "(file_redirect) @redirect"))
        self.q_assign = tree_sitter.QueryCursor(tree_sitter.Query(self.language, "(variable_assignment) @assign"))
        self.q_commands = tree_sitter.QueryCursor(tree_sitter.Query(self.language, "(command) @command"))
        self.q_heredocs = tree_sitter.QueryCursor(tree_sitter.Query(self.language, "(redirected_statement body: (command) @command redirect: (heredoc_redirect (heredoc_body) @body))"))
        self.depth = 0

    def call_name(self, call):
        name = call.child_by_field_name("name")
        return _text(name).rsplit("/", 1)[-1] if name is not None else None

    def call_args(self, call):
        return call.children_by_field_name("argument")

    def string_value(self, node):
        if node.type == "word":
            return _text(node)
        if node.type == "raw_string":
            return _text(node)[1:-1]
        parts = [c for c in node.children if c.type not in ('"',)]
        return _text(parts[0]) if len(parts) == 1 and parts[0].type == "string_content" else None

    def constant(self, node):
        at = node.parent
        while at is not None and at.type in ("string", "expansion", "concatenation"):
            at = at.parent
        if at is not None and at.type == "variable_assignment":
            name = at.child_by_field_name("name")
            return _text(name) if name is not None else None
        return None

    def flow(self, node):
        at = node.parent
        while at is not None and at.type in ("string", "concatenation"):
            at = at.parent
        if at is not None and at.type == "file_redirect":
            function, _call = self.context(node)
            return function, _redirect(at), {">": "write", ">>": "write", ">|": "write", "<": "read", "<>": "read and write"}.get(_redirect(at))
        return super().flow(node)

    def _variable_in(self, node) -> str | None:
        if node.type in ("simple_expansion", "expansion"):
            variable = next((c for c in node.children if c.type == "variable_name"), None)
            return _text(variable) if variable is not None else None
        if node.type == "string":
            inner = [c for c in node.children if c.type not in ('"',)]
            return self._variable_in(inner[0]) if len(inner) == 1 else None
        return None

    def _flows_of_call(self, callee, facts):
        call = callee.parent
        if call is None or call.type != "command":
            return
        function, name, access = self.flow(callee)
        if access is None:
            return
        for arg in self.call_args(call):
            variable = self._variable_in(arg)
            if variable:
                facts.flows.append((variable, _line(arg), function, name, access))

    def extra(self, root, source, facts):
        for redirect in _in_order(self.q_redirects, root):
            destination = redirect.child_by_field_name("destination")
            variable = self._variable_in(destination) if destination is not None else None
            if variable:
                function, _call = self.context(redirect)
                operator = _redirect(redirect)
                access = {">": "write", ">>": "write", ">|": "write", "<": "read", "<>": "read and write"}.get(operator)
                if access:
                    facts.flows.append((variable, _line(redirect), function, operator, access))
        for command in _in_order(self.q_commands, root):
            self._installs(command, facts)
        for assign in _in_order(self.q_assign, root):
            self._package_field(assign, facts)
        if self.depth < MAX_NESTED:
            self._nested_scripts(root, facts)

    def _installs(self, command, facts):
        name = self.call_name(command)
        verbs = _PACKAGE_MANAGERS.get(name or "")
        if not verbs:
            return
        words = [_text(a) for a in self.call_args(command)]
        at = next((i for i, w in enumerate(words) if w in verbs), None)
        if at is None:
            return
        function, _call = self.context(command)
        for word in words[at + 1:]:
            if _PACKAGE.fullmatch(word):
                facts.strings.append((word, "package", _line(command), "use", None, function, name, None))

    def _nested_scripts(self, root, facts):
        """`docker run … sh -c '…'` and `ssh host <<END`: much of what test scripts do happens inside a string like these."""
        scripts = []
        for node in _in_order(self.q_strings, root):
            # 'it'"'"'s' is several pieces side by side, each read on its own.
            whole = node.parent if node.parent is not None and node.parent.type == "concatenation" else node
            previous = whole.prev_named_sibling
            if node.type in ("raw_string", "string") and previous is not None and previous.text == b"-c":
                scripts.append((node.text[1:-1], node.start_point[0]))
        captured = self.q_heredocs.captures(root)
        names = {c.id: self.call_name(c) for c in captured.get("command", ())}
        for body in captured.get("body", ()):
            statement = body.parent.parent if body.parent is not None else None
            command = statement.child_by_field_name("body") if statement is not None else None
            if command is not None and names.get(command.id) in _RUNS_A_SCRIPT:
                scripts.append((body.text, body.start_point[0]))
        self.depth += 1
        try:
            for script, offset in scripts:
                inner = self.facts(script.replace(b'\\"', b'"'))
                facts.strings += [(s[0], s[1], s[2] + offset, *s[3:]) for s in inner.strings]
                facts.flows += [(f[0], f[1] + offset, *f[2:]) for f in inner.flows]
                for name, (count, lines) in inner.refs.items():
                    row = facts.refs.setdefault(name, [0, []])
                    row[0] += count
                    row[1] += [n + offset for n in lines]
        finally:
            self.depth -= 1

    def _package_field(self, assign, facts):
        name_node, value = assign.child_by_field_name("name"), assign.child_by_field_name("value")
        if name_node is None or value is None:
            return
        name = _text(name_node)
        if name == "pkgname" or name in _PACKAGE_FIELDS:
            text = _text(value).strip("\"'")
            for word in text.split():
                if _PACKAGE.fullmatch(word):
                    facts.strings.append((word, "package", _line(assign), "define" if name == "pkgname" else "use", None, None, name, None))


def _redirect(node) -> str | None:
    for child in node.children:
        if not child.is_named and child.type in (">", ">>", ">|", "<", "<>", "&>", "&>>"):
            return child.type
    return None


_C_LANGUAGE = tree_sitter.Language(tree_sitter_c.language())
_PREPROC_CURSOR = tree_sitter.QueryCursor(tree_sitter.Query(_C_LANGUAGE, "(preproc_arg) @arg"))
_READERS: dict[str, _Language] = {}
_MAKERS = {"c": (_C, tree_sitter_c.language), "python": (_Python, tree_sitter_python.language), "javascript": (_JavaScript, tree_sitter_javascript.language),
           "shell": (_Shell, tree_sitter_bash.language), "rust": (_Rust, tree_sitter_rust.language)}


def extract(language: str, source: bytes) -> Facts:
    reader = _READERS.get(language)
    if reader is None:
        maker, grammar = _MAKERS[language]
        reader = _READERS[language] = maker(grammar())
    return reader.facts(source).settle()
