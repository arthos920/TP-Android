echo "export GNOME_SHELL_SESSION_MODE=ubuntu" > ~/.xsession
echo "export XDG_CURRENT_DESKTOP=ubuntu:GNOME" >> ~/.xsession
echo "export XDG_SESSION_TYPE=x11" >> ~/.xsession
echo "exec gnome-session --session=ubuntu" >> ~/.xsession
chmod +x ~/.xsession
sudo systemctl restart xrdp