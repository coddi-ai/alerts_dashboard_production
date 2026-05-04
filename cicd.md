```sh
PROD=618780608734
TEST=484907511862
DEVE=423623830618
SAND=513947710455

ACCOUNT=${DEVE}

docker build -t alerts-dashboard .

aws --profile development ecr get-login-password --region sa-east-1 | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.sa-east-1.amazonaws.com"

docker tag alerts-dashboard:latest "${ACCOUNT}.dkr.ecr.sa-east-1.amazonaws.com/837fb858325fec-alerts-dashboard:latest"

docker push "${ACCOUNT}.dkr.ecr.sa-east-1.amazonaws.com/837fb858325fec-alerts-dashboard:latest"
```

## Debugging

```shell
docker run -p 8050:8050 -it alerts-dashboard:latest bash

python dashboard/app.py
```
