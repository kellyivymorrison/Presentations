#!/usr/bin/env python3

import re
from pathlib import Path
from collections import defaultdict

OUTPUT_FILE = "DEPENDENCIES.md"


# ---------- Helpers ----------

def walk_repo(root="."):
    for path in Path(root).rglob("*"):
        if any(p in path.parts for p in [".git", "node_modules", "venv", "__pycache__"]):
            continue
        if path.is_file():
            yield path


def read_file(path):
    try:
        return path.read_text(encoding="utf-8")
    except:
        return ""


# ---------- Detection Patterns ----------

DB_PATTERNS = [
    ("PostgreSQL", r'jdbc:postgresql://'),
    ("MySQL", r'jdbc:mysql://'),
    ("Oracle", r'jdbc:oracle:'),
    ("SQL Server", r'jdbc:sqlserver://'),
    ("MongoDB", r'mongodb://'),
    ("Redis", r'redis://'),
]

ORM_PATTERNS = [
    ("Hibernate/JPA", r'@Entity|EntityManager|JpaRepository'),
]

JS_DB_LIBS = [
    ("PostgreSQL", r'require\(["\']pg["\']\)|from ["\']pg["\']'),
    ("MongoDB", r'mongoose'),
    ("MySQL", r'mysql'),
]


REST_PATTERNS = [
    ("Java RestTemplate", r'RestTemplate'),
    ("Java WebClient", r'WebClient'),
    ("Java HttpClient", r'HttpClient'),
    ("JS fetch", r'\bfetch\('),
    ("JS axios", r'axios'),
]


SHELL_PATTERNS = [
    ("Java Runtime.exec", r'Runtime\.getRuntime\(\)\.exec'),
    ("Java ProcessBuilder", r'ProcessBuilder'),
    ("Node exec", r'child_process\.exec'),
    ("Node spawn", r'child_process\.spawn'),
]


MESSAGING_PATTERNS = [
    ("Kafka", r'KafkaProducer|KafkaConsumer'),
    ("Google PubSub", r'PubSub|@google-cloud/pubsub'),
    ("RabbitMQ", r'RabbitMQ|amqp'),
]


# ---------- Analysis ----------

def analyze_repo():
    db_usage = defaultdict(list)
    rest_calls = defaultdict(list)
    shell_usage = defaultdict(list)
    messaging_usage = defaultdict(list)

    for path in walk_repo("."):
        text = read_file(path)

        if not text:
            continue

        # Databases
        for name, pattern in DB_PATTERNS:
            if re.search(pattern, text):
                db_usage[name].append(str(path))

        for name, pattern in ORM_PATTERNS:
            if re.search(pattern, text):
                db_usage[name].append(str(path))

        for name, pattern in JS_DB_LIBS:
            if re.search(pattern, text):
                db_usage[name].append(str(path))

        # REST
        for name, pattern in REST_PATTERNS:
            if re.search(pattern, text):
                rest_calls[name].append(str(path))

        # Shell
        for name, pattern in SHELL_PATTERNS:
            if re.search(pattern, text):
                shell_usage[name].append(str(path))

        # Messaging
        for name, pattern in MESSAGING_PATTERNS:
            if re.search(pattern, text):
                messaging_usage[name].append(str(path))

    return db_usage, rest_calls, shell_usage, messaging_usage


# ---------- Markdown ----------

def write_markdown(db, rest, shell, messaging):
    with open(OUTPUT_FILE, "w") as f:
        f.write("# Dependency Analysis\n\n")

        # Databases
        f.write("## Databases\n\n")
        for db_name, files in db.items():
            f.write(f"### {db_name}\n")
            for file in sorted(set(files)):
                f.write(f"- {file}\n")
            f.write("\n")

        # REST
        f.write("## External REST Calls\n\n")
        for name, files in rest.items():
            f.write(f"### {name}\n")
            for file in sorted(set(files)):
                f.write(f"- {file}\n")
            f.write("\n")

        # Shell
        f.write("## Shell / External Program Execution\n\n")
        for name, files in shell.items():
            f.write(f"### {name}\n")
            for file in sorted(set(files)):
                f.write(f"- {file}\n")
            f.write("\n")

        # Messaging
        f.write("## Messaging Systems\n\n")
        for name, files in messaging.items():
            f.write(f"### {name}\n")
            for file in sorted(set(files)):
                f.write(f"- {file}\n")
            f.write("\n")


# ---------- Main ----------

def main():
    db, rest, shell, messaging = analyze_repo()
    write_markdown(db, rest, shell, messaging)
    print(f"Dependency report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

