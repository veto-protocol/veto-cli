from setuptools import setup, find_packages

setup(
    name="veto-cli",
    version="0.1.0",
    description="Veto CLI — one-command MCP setup for AI agent authorization",
    long_description=(
        "The Veto CLI auto-configures MCP (Model Context Protocol) for your AI agents. "
        "Protects every transaction your agent makes: Claude Desktop, Cursor, ChatGPT, and more."
    ),
    long_description_content_type="text/markdown",
    author="Veto",
    author_email="tomer@veto-ai.com",
    url="https://veto-ai.com",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],  # stdlib only — keep install frictionless
    entry_points={
        "console_scripts": [
            "veto=veto_cli.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries",
        "Programming Language :: Python :: 3",
    ],
)
