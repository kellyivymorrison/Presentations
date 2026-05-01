#!/usr/bin/env python3

import ast
from pathlib import Path
from collections import defaultdict
import re
import yaml

OUTPUT_FILE = "CONFIGURATION.md"


# ---------- Helpers ----------

def walk_repo(root="."):
    for path in Path(root).rglob("*"):
        if any(part in path.parts for part in [".git", "venv", "__pycache__", "node_modules"]):
            continue
        if path.is_file():
            yield path


def is_python_file(path):
    return path.suffix == ".py"


def is_java_file(path):
    return path.suffix == ".java"


def is_config_filename(name):
    return any(name.endswith(ext) for ext in [
        ".yaml", ".yml", ".json", ".ini", ".cfg", ".toml"
    ])


# ---------- Python AST Visitor ----------

class ConfigVisitor(ast.NodeVisitor):
    def __init__(self):
        self.env_vars = []
        self.cli_args = []
        self.config_files = set()

    def visit_Call(self, node):
        # os.getenv
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "getenv":
                if node.args:
                    name = get_str(node.args[0])
                    default = get_str(node.args[1]) if len(node.args) > 1 else None
                    if name:
                        self.env_vars.append((name, default, self.current_file))

        # argparse
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                arg_name = get_str(node.args[0]) if node.args else None
                default = None
                help_text = None

                for kw in node.keywords:
                    if kw.arg == "default":
                        default = get_str(kw.value)
                    elif kw.arg == "help":
                        help_text = get_str(kw.value)

                if arg_name:
                    self.cli_args.append((arg_name, default, help_text, self.current_file))

        # open(config.*)
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            if node.args:
                fname = get_str(node.args[0])
                if fname and is_config_filename(fname):
                    self.config_files.add(fname)

        self.generic_visit(node)

    def visit_Subscript(self, node):
        # os.environ["FOO"]
        if isinstance(node.value, ast.Attribute):
            if node.value.attr == "environ":
                key = get_str(node.slice)
                if key:
                    self.env_vars.append((key, None, self.current_file))
        self.generic_visit(node)


# ---------- Picocli Parsing (Java) ----------

PICOCLI_OPTION_REGEX = re.compile(
    r'@Option\s*\(\s*names\s*=\s*\{?([^}]+)\}?.*?(description\s*=\s*"([^"]*)")?.*?(defaultValue\s*=\s*"([^"]*)")?',
    re.DOTALL
)

PICOCLI_PARAM_REGEX = re.compile(
    r'@Parameters\s*\((.*?)\)',
    re.DOTALL
)


def parse_picocli_java(path):
    cli_args = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return cli_args

    for match in PICOCLI_OPTION_REGEX.finditer(text):
        names = match.group(1)
        description = match.group(3)
        default = match.group(5)

        if names:
            for name in re.findall(r'"([^"]+)"', names):
                cli_args.append((name, default, description, str(path)))

    for match in PICOCLI_PARAM_REGEX.finditer(text):
        cli_args.append(("<positional>", None, match.group(1), str(path)))

    return cli_args


# ---------- Docker Parsing ----------

def parse_dockerfile(path):
    env_vars = []
    args = []
    ports = []
    commands = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line.startswith("ENV"):
                for part in line.split()[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        env_vars.append((k, v, str(path)))

            elif line.startswith("ARG"):
                for part in line.split()[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                    else:
                        k, v = part, None
                    args.append((k, v, str(path)))

            elif line.startswith("EXPOSE"):
                ports.extend(line.split()[1:])

            elif line.startswith(("CMD", "ENTRYPOINT")):
                commands.append(line)

    return env_vars, args, ports, commands


def parse_docker_compose(path):
    env_vars = []
    try:
        data = yaml.safe_load(path.read_text())
    except Exception:
        return env_vars

    services = data.get("services", {})
    for svc, config in services.items():
        env = config.get("environment", {})
        if isinstance(env, dict):
            for k, v in env.items():
                env_vars.append((k, v, f"{path}:{svc}"))
        elif isinstance(env, list):
            for item in env:
                if "=" in item:
                    k, v = item.split("=", 1)
                    env_vars.append((k, v, f"{path}:{svc}"))

    return env_vars


def parse_dotenv(path):
    env_vars = []
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars.append((k.strip(), v.strip(), str(path)))
    return env_vars


# ---------- Utility ----------

def get_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# ---------- Main Analysis ----------

def analyze_repo(root="."):
    visitor = ConfigVisitor()

    docker_env = []
    docker_args = []
    docker_ports = []
    docker_commands = []

    java_cli_args = []

    for path in walk_repo(root):
        try:
            if is_python_file(path):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                visitor.current_file = str(path)
                visitor.visit(tree)

            elif is_java_file(path):
                java_cli_args.extend(parse_picocli_java(path))

            elif path.name == "Dockerfile":
                env, args, ports, commands = parse_dockerfile(path)
                docker_env.extend(env)
                docker_args.extend(args)
                docker_ports.extend(ports)
                docker_commands.extend(commands)

            elif path.name in ("docker-compose.yml", "docker-compose.yaml"):
                docker_env.extend(parse_docker_compose(path))

            elif path.name == ".env":
                docker_env.extend(parse_dotenv(path))

        except Exception:
            continue

    return visitor, docker_env, docker_args, docker_ports, docker_commands, java_cli_args


# ---------- Markdown ----------

def write_markdown(visitor, docker_env, docker_args, docker_ports, docker_commands, java_cli_args):
    with open(OUTPUT_FILE, "w") as f:
        f.write("# Configuration Analysis\n\n")

        # ENV VARS
        f.write("## Environment Variables\n\n")
        f.write("| Name | Default | Source |\n|------|--------|--------|\n")
        for name, default, src in sorted(visitor.env_vars + docker_env):
            f.write(f"| {name} | {default or ''} | {src} |\n")

        # CLI (Python + Picocli)
        f.write("\n## Command Line Arguments\n\n")
        f.write("| Argument | Default | Description | Source |\n")
        f.write("|----------|--------|-------------|--------|\n")

        for name, default, desc, src in sorted(visitor.cli_args + java_cli_args):
            f.write(f"| {name} | {default or ''} | {desc or ''} | {src} |\n")

        # CONFIG FILES
        f.write("\n## Configuration Files\n\n")
        f.write("| File |\n|------|\n")
        for file in sorted(visitor.config_files):
            f.write(f"| {file} |\n")

        # Docker
        f.write("\n## Docker Configuration\n\n")

        f.write("### Build Arguments (ARG)\n\n")
        f.write("| Name | Default | Source |\n|------|--------|--------|\n")
        for name, default, src in docker_args:
            f.write(f"| {name} | {default or ''} | {src} |\n")

        f.write("\n### Exposed Ports\n\n")
        for port in docker_ports:
            f.write(f"- {port}\n")

        f.write("\n### Entrypoints / Commands\n\n")
        for cmd in docker_commands:
            f.write(f"- `{cmd}`\n")


# ---------- Main ----------

def main():
    results = analyze_repo(".")
    write_markdown(*results)
    print(f"Configuration written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

