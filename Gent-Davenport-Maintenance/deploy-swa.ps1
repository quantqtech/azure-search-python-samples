$token = az staticwebapp secrets list --name swa-davenport-support --resource-group rg-gent-foundry-eus2 --query "properties.apiKey" -o tsv
cd "c:\repos\azure-search-python-samples\Gent-Davenport-Maintenance\static-web-app"
swa deploy src --deployment-token $token --env production
