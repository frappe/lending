#!/bin/bash

set -e

cd ~ || exit

sudo apt-get update
sudo apt-get -y install redis-server libcups2-dev -qq

pip install frappe-bench

git clone https://github.com/frappe/frappe --branch "$BRANCH_TO_CLONE" --depth 1
bench init --skip-assets --frappe-path ~/frappe --python "$(which python)" frappe-bench

mkdir ~/frappe-bench/sites/test_site
cp -r "${GITHUB_WORKSPACE}/.github/helper/site_config.json" ~/frappe-bench/sites/test_site/

mysql --host 127.0.0.1 --port 3306 -u root -e "SET GLOBAL character_set_server = 'utf8mb4'"
mysql --host 127.0.0.1 --port 3306 -u root -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'"

mysql --host 127.0.0.1 --port 3306 -u root -e "CREATE USER 'test_frappe'@'localhost' IDENTIFIED BY 'test_frappe'"
mysql --host 127.0.0.1 --port 3306 -u root -e "CREATE DATABASE test_frappe"
mysql --host 127.0.0.1 --port 3306 -u root -e "GRANT ALL PRIVILEGES ON \`test_frappe\`.* TO 'test_frappe'@'localhost'"

mysql --host 127.0.0.1 --port 3306 -u root -e "UPDATE mysql.user SET Password=PASSWORD('travis') WHERE User='root'"
mysql --host 127.0.0.1 --port 3306 -u root -e "FLUSH PRIVILEGES"

install_whktml() {
    wget -O /tmp/wkhtmltox.tar.xz https://github.com/frappe/wkhtmltopdf/raw/master/wkhtmltox-0.12.3_linux-generic-amd64.tar.xz
    tar -xf /tmp/wkhtmltox.tar.xz -C /tmp
    sudo mv /tmp/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf
    sudo chmod o+x /usr/local/bin/wkhtmltopdf
}
install_whktml &

cd ~/frappe-bench || exit

sed -i 's/watch:/# watch:/g' Procfile
sed -i 's/schedule:/# schedule:/g' Procfile
sed -i 's/socketio:/# socketio:/g' Procfile
sed -i 's/redis_socketio:/# redis_socketio:/g' Procfile

bench get-app payments
bench get-app https://github.com/frappe/erpnext --branch develop --resolve-deps
bench setup requirements --dev

bench start &> bench_run_logs.txt &
CI=Yes bench build --app frappe &
bench --site test_site reinstall --yes

bench get-app lending "${GITHUB_WORKSPACE}"
bench --site test_site install-app lending
bench setup requirements --dev