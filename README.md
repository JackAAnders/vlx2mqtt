# vlx2mqtt
pyvlx to MQTT glue

# configuration file
adjust configuration file to your needs

# installation
## docker
just start docker compose up -d

## service
install the requirements for python with `pip install -r requirements.txt`

copy `vlx.service` to /etc/systemd/system/

`systemctl start vlx`
