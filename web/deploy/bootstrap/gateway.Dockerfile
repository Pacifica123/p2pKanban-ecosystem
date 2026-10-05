FROM nginx:1.27-alpine

COPY deploy/bootstrap/gateway.conf /etc/nginx/conf.d/default.conf
COPY deploy/bootstrap/maintenance.html /usr/share/nginx/html/maintenance.html
