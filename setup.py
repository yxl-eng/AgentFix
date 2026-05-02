from __future__ import annotations

from setuptools import find_packages, setup


setup(
    name="agentfix",
    version="0.1.0",
    description="Agent-based service auto-repair CLI for web service repositories",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.10",
    install_requires=[
        "openai>=1.0.0,<3",
        "pydantic>=2.8.0,<3",
        "PyYAML>=6.0,<7",
        "tenacity>=8.0.0,<9",
    ],
    extras_require={"dev": ["pytest>=8.0.0,<9"]},
    entry_points={"console_scripts": ["agentfix=agentfix.cli:main"]},
)
