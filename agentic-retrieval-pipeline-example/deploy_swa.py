"""
Deploy Static Web App files using Azure REST API.
"""

import os
import base64
import json
import subprocess

# Get deployment token
result = subprocess.run(
    ["az", "staticwebapp", "secrets", "list", "--name", "swa-davenport-support",
     "--resource-group", "rg-gent-foundry-eus2", "--query", "properties.apiKey", "-o", "tsv"],
    capture_output=True, text=True
)
token = result.stdout.strip()

# Read index.html
with open(r"c:\repos\azure-search-python-samples\agentic-retrieval-pipeline-example\static-web-app\src\index.html", "r") as f:
    content = f.read()

print(f"Token length: {len(token)}")
print(f"Content length: {len(content)}")

# Create zip file for deployment
import zipfile
import io

zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('index.html', content)
    # Add config
    with open(r"c:\repos\azure-search-python-samples\agentic-retrieval-pipeline-example\static-web-app\src\staticwebapp.config.json", "r") as f:
        zf.writestr('staticwebapp.config.json', f.read())

# Save zip file
zip_path = r"c:\repos\azure-search-python-samples\agentic-retrieval-pipeline-example\static-web-app\deploy.zip"
with open(zip_path, 'wb') as f:
    f.write(zip_buffer.getvalue())

print(f"Created deployment zip at: {zip_path}")
print(f"Zip size: {len(zip_buffer.getvalue())} bytes")

# Deploy using swa cli with zip
print("\nDeploying...")
import subprocess
result = subprocess.run(
    ["swa", "deploy", zip_path, "--deployment-token", token, "--env", "production"],
    capture_output=True, text=True, timeout=60
)
print(result.stdout)
print(result.stderr)
