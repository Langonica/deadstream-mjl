#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
version=v2
image_date=`date +%Y%m%d`
image_name=$version\_$image_date
media_folder=/media/steve

while [[ $# -gt 0 ]]
do
key=$1

case $key in 
	-n | --name)
	image_name=$2; shift; shift
	;;
	-f | --folder)
	media_folder=$2; shift; shift
	;;
	-h | --help)
	echo "Usage: $0 [-n image_name] [-f media_folder] [-h]"
	exit 0
	;;
	*)
	POSITIONAL+=("$1")
	shift
	;;
esac
done

set -- "${POSITIONAL[@]}"
image_file=$SCRIPT_DIR/$image_name.img
echo "image_file is ${image_file}, media_folder is ${media_folder}"

critical_command () {
   command=$1
   echo "$command"
   $command
   stat=$?
   echo "Status $stat"
   if [ $stat != 0 ]; then
      exit $stat
   fi
}

system () {
   command=$1
   echo "$command"
   $command
}


echo "Removing previous git folders"
system "cd $media_folder/rootfs/home/deadhead"
current_env=$(basename `readlink -f timemachine`)
files=`find . -maxdepth 1 -mindepth 1 -name env_\* -a -not -name $current_env -printf "%f "`
system "sudo rm -rf $files"
system "sudo mv .knob_sense $HOME/.knob_sense"
system "sudo mv .timemachine_options.txt $HOME/.timemachine_options.txt"
system "sudo mv .ssh $HOME/timemachine_dot_ssh"
system "sudo rm -rf .ssh .bash_history .python_history .viminfo .wget-hsts .gnupg .lesshst .ipython .local .gitconfig .xsession*"
system "sudo rm -rf .factory_env"
system "sudo cp -r $current_env .factory_env"
system "sudo cp $HOME/test_sound.ogg ."


echo "Removing wpa_supplicant"
system "sudo mv $media_folder/rootfs/etc/wpa_supplicant/wpa_supplicant.conf $HOME/wpa_supplicant.conf"
system "sudo rm $media_folder/rootfs/etc/wpa_supplicant/wpa_supplicant.conf*"

media_dirs="/dev/sdb1 /dev/sdb2"

for dir in $media_dirs; do
    system "sudo umount $dir"
done

system "sudo rm $image_file"
critical_command "sudo dd if=/dev/sdb of=$image_file bs=4M status=progress"

system "sudo pishrink.sh $image_file"
echo "Replacing wpa_supplicant and knob_sense files"
system "sudo mv $HOME/wpa_supplicant.conf $media_folder/rootfs/etc/wpa_supplicant/wpa_supplicant.conf"
system "sudo mv $HOME/.knob_sense $media_folder/rootfs/home/deadhead/."
system "sudo mv $HOME/.timemachine_options.txt $media_folder/rootfs/home/deadhead/."
system "sudo mv $HOME/timemachine_dot_ssh $media_folder/rootfs/home/deadhead/.ssh"

# NOTE: to burn an image use the command (or similar):
# sudo sh -c "pv v2_20210625.img > /dev/sdb"
# ./balenaEtcher-1.5.120-x64.AppImage > /dev/null 2>&1 &
