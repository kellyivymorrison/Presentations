#!/usr/bin/env python3

import re
import json
import requests
from pathlib import Path
import xml.etree.ElementTree as ET

OUTPUT_FILE = "SECURITY.md"


# ---------- Helpers ----------

def walk_repo(root="."):
    for path in Path(root).rglob("*"):
        if any(p in path.parts for p in [".git", "node_modules", "venv", "__pycache__"]):
            continue
        if path.is_file():
            yield path


# ---------- Spring Boot Endpoint Detection ----------

ENDPOINT_REGEX = re.compile(r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\((.*?)\)')
SECURITY_ANNOTATIONS = ["PreAuthorize", "Secured", "RolesAllowed"]


def analyze_java_endpoints(path):
    endpoints = []

    try:
        text = path.read_text(encoding="utf-8")
    except:
        return endpoints

    for match in ENDPOINT_REGEX.finditer(text):
        annotation = match.group(1)
        args = match.group(2)

        secured = any(f"@{sec}" in text for sec in SECURITY_ANNOTATIONS)

        endpoints.append({
            "file": str(path),
            "mapping": annotation,
            "args": args,
            "secured": secured
        })

    return endpoints


# ---------- Java Security Checks ----------

JAVA_ISSUES = [
    ("Hardcoded Secret", r'password\s*=\s*".+"'),
    ("Weak Crypto", r'MD5|SHA1'),
    ("SQL Injection Risk", r'Statement\s+.*executeQuery'),
    ("Command Execution", r'Runtime\.getRuntime\(\)\.exec'),
]


def analyze_java_security(path):
    findings = []

    try:
        text = path.read_text(encoding="utf-8")
    except:
        return findings

    for label, pattern in JAVA_ISSUES:
        if re.search(pattern, text):
            findings.append((label, str(path)))

    return findings


# ---------- JavaScript Security Checks ----------

JS_ISSUES = [
    ("eval usage", r'\beval\('),
    ("innerHTML usage", r'\.innerHTML\s*='),
    ("Hardcoded Secret", r'(api_key|secret|token)\s*=\s*["\']'),
]


def analyze_js_security(path):
    findings = []

    try:
        text = path.read_text(encoding="utf-8")
    except:
        return findings

    for label, pattern in JS_ISSUES:
        if re.search(pattern, text):
            findings.append((label, str(path)))

    return findings


# ---------- Dependency Extraction ----------

def parse_pom(path):
    deps = []

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except:
        return deps

    ns = {"m": "http://maven.apache.org/POM/4.0.0"}

    for dep in root.findall(".//m:dependency", ns):
        group = dep.find("m:groupId", ns)
        artifact = dep.find("m:artifactId", ns)
        version = dep.find("m:version", ns)

        if group is not None and artifact is not None:
            deps.append({
                "name": f"{group.text}:{artifact.text}",
                "version": version.text if version is not None else None
            })

    return deps


def parse_package_json(path):
    deps = []

    try:
        data = json.loads(path.read_text())
    except:
        return deps

    for section in ["dependencies", "devDependencies"]:
        for name, version in data.get(section, {}).items():
            deps.append({"name": name, "version": version})

    return deps


# ---------- CVE via OSV ----------

def check_osv(dep):
    url = "https://api.osv.dev/v1/query"
    payload = {
        "package": {"name": dep["name"]},
        "version": dep["version"]
    }

    try:
        r = requests.post(url, json=payload, timeout=5)
        data = r.json()
        return data.get("vulns", [])
    except:
        return []


# ---------- Main ----------

def main():
    endpoints = []
    java_findings = []
    js_findings = []
    dependencies = []
    vulnerabilities = []

    for path in walk_repo("."):
        if path.suffix == ".java":
            endpoints.extend(analyze_java_endpoints(path))
            java_findings.extend(analyze_java_security(path))

        elif path.suffix in [".js", ".jsx", ".ts"]:
            js_findings.extend(analyze_js_security(path))

        elif path.name == "pom.xml":
            dependencies.extend(parse_pom(path))

        elif path.name == "package.json":
            dependencies.extend(parse_package_json(path))

    # CVE checks (limit for sanity)
    for dep in dependencies[:50]:
        vulns = check_osv(dep)
        if vulns:
            vulnerabilities.append((dep, vulns))

    # ---------- Write Markdown ----------

    with open(OUTPUT_FILE, "w") as f:
        f.write("# Security Analysis\n\n")

        # Endpoints
        f.write("## REST API Endpoints\n\n")
        f.write("| File | Mapping | Args | Secured |\n")
        f.write("|------|--------|------|----------|\n")
        for ep in endpoints:
            status = "SECURED" if ep["secured"] else "POSSIBLY UNSECURED"
            f.write(f"| {ep['file']} | {ep['mapping']} | {ep['args']} | {status} |\n")

        # Java issues
        f.write("\n## Java Security Findings\n\n")
        for label, file in java_findings:
            f.write(f"- {label}: {file}\n")

        # JS issues
        f.write("\n## JavaScript Security Findings\n\n")
        for label, file in js_findings:
            f.write(f"- {label}: {file}\n")

        # CVEs
        f.write("\n## Dependency Vulnerabilities (CVE)\n\n")
        for dep, vulns in vulnerabilities:
            f.write(f"### {dep['name']} {dep['version']}\n")
            for v in vulns:
                f.write(f"- {v.get('id')} ({v.get('summary', '')})\n")

    print(f"Security report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
