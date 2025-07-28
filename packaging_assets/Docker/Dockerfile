# Get and install Easy noVNC.
FROM golang:1.22.0-bookworm AS easy-novnc-build
WORKDIR /src
RUN go mod init build && go get github.com/geek1011/easy-novnc@v1.1.0 && go build -o /bin/easy-novnc github.com/geek1011/easy-novnc

# Get TigerVNC and Supervisor for isolating the container.
FROM ubuntu:latest
RUN apt-get update -y && apt-get install -y --no-install-recommends openbox locales tigervnc-standalone-server supervisor gosu lxterminal nano wget ca-certificates xdg-utils htop && rm -rf /var/lib/apt/lists

RUN mkdir -p /CarveraController/
WORKDIR /CarveraController

# Copy the locally built AppImage artifact
COPY artifacts/*.appimage ./carveracontroller.appimage
RUN chmod +x carveracontroller.appimage

# Add the user
RUN groupadd carveracontroller && useradd -g carveracontroller --create-home --home-dir /config carveracontroller && chown -R carveracontroller:carveracontroller  /config

# Set the locale for english
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

COPY --from=easy-novnc-build /bin/easy-novnc /usr/local/bin/
COPY menu.xml /etc/xdg/openbox/
COPY supervisord.conf /etc/


# VNC Port
EXPOSE 5900
# HTTP Port
EXPOSE 8080

WORKDIR /config

VOLUME /config

CMD ["bash", "-c", "chown -R carveracontroller:carveracontroller  /config /dev/stdout && exec gosu carveracontroller supervisord"]