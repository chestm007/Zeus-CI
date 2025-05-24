set -e

echo "building $1"
rm -rf temp_dir
mkdir temp_dir
mkdir temp_dir/mods

USER_SPECIFIED_VERSION=$1
BASE_IMAGE=quay.io/chestm007/alpine-base

echo 'updating base image'
docker pull $BASE_IMAGE

# Download USER_SPECIFIED_VERSION of minecraft jar.
VERSIONS="$(wget -q -O - "https://launchermeta.mojang.com/mc/game/version_manifest.json" )"
VERSION_URL=$(echo "${VERSIONS}" | jq -r ".versions[] | select(.id == \"${USER_SPECIFIED_VERSION}\").url")
JAR_URL="$(curl -s ${VERSION_URL} | jq -r ".downloads.server.url")"
#echo "downloading server: $JAR_URL"
wget -nv --show-progress -O temp_dir/server.jar $JAR_URL

echo "downloading fabric..."
FABRIC_INSTALLER_VERSION=$(wget -q -O - https://meta.fabricmc.net/v2/versions/installer | jq -r ".[] | select(.stable == true)" | jq -r ".version")
FABRIC_LOADER_VERSION=$(wget -q -O - https://meta.fabricmc.net/v2/versions/loader/$USER_SPECIFIED_VERSION | jq -r ".[] | select(.loader.stable == true)" | jq -r ".loader.version")
wget -q -O temp_dir/fabric-server-launch.jar https://meta.fabricmc.net/v2/versions/loader/$USER_SPECIFIED_VERSION/$FABRIC_LOADER_VERSION/$FABRIC_INSTALLER_VERSION/server/jar

function from_url {
  #echo "downloading mod: $2"
  wget -nv --show-progress -O temp_dir/mods/$1.jar $2
}

function carpet_from_asset {
  cp ../assets/$2 temp_dir/mods/$1.jar
}

# autodetect and install the right mix of carpet, carpet-extra and carpet-autocrafting based on user version.
if [[ $USER_SPECIFIED_VERSION == '1.16' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/v1.4-homebound/fabric-carpet-1.16.1-1.4.0+v200623_build2.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/v1.4/carpet-extra-1.16-1.4.0.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/v1.4/carpet-autocraftingtable-1.16-1.4.0.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.16.1' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/v1.4-homebound/fabric-carpet-1.16.1-1.4.0+v200623_build2.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/v1.4/carpet-extra-1.16-1.4.0.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/v1.4/carpet-autocraftingtable-1.16-1.4.0.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.16.2' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/v1.4-homebound/fabric-carpet-1.16.2-1.4.9+v200815.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/v1.4/carpet-extra-1.16.2-1.4.8.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/v1.4/carpet-autocraftingtable-1.16.3-1.4.11.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.16.4' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/v1.4-homebound/fabric-carpet-1.16.4-1.4.17+v201111.jar'
  # from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/v1.4-homebound/fabric-carpet-20w48a-1.4.19+v201125.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/v1.4/carpet-extra-1.16.4-1.4.16.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/v1.4/carpet-autocraftingtable-1.16.4-1.4.17_build2.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.16.5' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/1.4.44/fabric-carpet-1.16.5-1.4.44+v210714.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/1.4.43/carpet-extra-1.16.5-1.4.43.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/v1.4/carpet-autocraftingtable-1.16.4-1.4.17_build2.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.17' ]]; then
  from_url fabric-carpet 'https://github.com/gnembon/fabric-carpet/releases/download/1.4.40/fabric-carpet-1.17-1.4.40+v210608.jar'
  from_url carpet-extra 'https://github.com/gnembon/carpet-extra/releases/download/1.4.40/carpet-extra-1.17-1.4.40.jar'
  from_url carpet-autocraftingtable 'https://github.com/gnembon/carpet-autoCraftingTable/releases/download/1.4.39/carpet-autocraftingtable-1.17-1.4.39.jar'

elif [[ $USER_SPECIFIED_VERSION == '1.18.1' ]]; then
  echo

else
  python3 carpet_version_finder.py $USER_SPECIFIED_VERSION

fi

DOCKER_IMAGE=quay.io/chestm007/minecraft-alpine:$USER_SPECIFIED_VERSION

DOCKER_BUILDKIT=1

# DO THE ROAR
echo 'building...'
docker build -t $DOCKER_IMAGE .
echo 'pushing...'
docker push ${DOCKER_IMAGE}


rm -rf temp_dir

exit 0

elif [[ $USER_SPECIFIED_VERSION == '1.16.5' ]]; then
  from_url fabric-carpet
  from_url carpet-extra
  from_url carpet-autocraftingtable

