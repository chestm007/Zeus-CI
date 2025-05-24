FROM quay.io/chestm007/alpine-base:latest
MAINTAINER Max Chesterfield


ARG server_dir=/srv/minecraft
WORKDIR ${server_dir}
COPY launcher.sh /usr/local/bin/minecraft_launcher.sh
COPY temp_dir/server.jar ${server_dir}/server.jar
COPY temp_dir/mods ${server_dir}/mods

COPY temp_dir/fabric-server-launch.jar ${server_dir}/fabric-server-launch.jar

