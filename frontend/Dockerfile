FROM nginxinc/nginx-unprivileged:alpine

COPY index.html /usr/share/nginx/html/index.html
COPY app.js /usr/share/nginx/html/app.js
COPY nginx.conf /etc/nginx/templates/default.conf.template

EXPOSE 8080
