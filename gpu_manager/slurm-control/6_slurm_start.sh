sudo chmod 600 /etc/slurm/slurmdbd.conf
sudo chown slurm:slurm /etc/slurm/slurmdbd.conf
sudo chown slurm:slurm /etc/slurm/slurm.conf
sudo chown slurm:slurm /var/spool/slurmctld
sudo systemctl enable slurmdbd && sudo systemctl start slurmdbd
sudo systemctl enable slurmctld && sudo systemctl start slurmctld && sudo systemctl status slurmctld
