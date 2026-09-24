# TLS front for the read-only web interface. One upstream, no cache, no application logic:
# everything it does is terminate TLS and hand the request to the interface.
FROM nginx:alpine

RUN apk add --no-cache openssl gettext

COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443
ENTRYPOINT ["/entrypoint.sh"]
