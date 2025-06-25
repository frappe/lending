#!/bin/bash

set -e

cd ~ || exit

sudo apt update
sudo apt remove mysql-server mysql-client
sudo apt install libcups2-dev redis-server mariadb-client

pip install frappe-bench

LENDING_BRANCH=${BRANCH_TO_CLONE:-develop}

if [[ "$LENDING_BRANCH" == "version-1" || "$LENDING_BRANCH" == "version-1-hotfix" ]]; then
    FRAPPE_BRANCH="version-15"
    ERPNEXT_BRANCH="version-15"
else
    FRAPPE_BRANCH="develop"
    ERPNEXT_BRANCH="develop"
fi

echo "Using Frappe branch: $FRAPPE_BRANCH"
echo "Using ERPNext branch: $ERPNEXT_BRANCH"
echo "Using Lending branch: $LENDING_BRANCH"

git clone https://github.com/frappe/frappe --branch $FRAPPE_BRANCH --depth 1
bench init --skip-assets --frappe-path ~/frappe --python "$(which python)" frappe-bench

mkdir ~/frappe-bench/sites/test_site
cp -r "${GITHUB_WORKSPACE}/.github/helper/site_config.json" ~/frappe-bench/sites/test_site/

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL character_set_server = 'utf8mb4'"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'"

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "CREATE USER 'test_frappe'@'localhost' IDENTIFIED BY 'test_frappe'"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "CREATE DATABASE test_frappe"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "GRANT ALL PRIVILEGES ON \`test_frappe\`.* TO 'test_frappe'@'localhost'"

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "FLUSH PRIVILEGES"

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
bench get-app https://github.com/frappe/erpnext --branch $ERPNEXT_BRANCH --resolve-deps
bench setup requirements --dev

bench start &> bench_run_logs.txt &
CI=Yes bench build --app frappe &
bench --site test_site reinstall --yes

bench get-app "${GITHUB_WORKSPACE}"
bench --site test_site install-app lending
bench setup requirements --dev
