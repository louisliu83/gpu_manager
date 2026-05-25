CREATE USER 'slurm'@'localhost' IDENTIFIED BY 'your_secure_password';
CREATE DATABASE slurm_acct_db;
GRANT ALL ON slurm_acct_db.* TO 'slurm'@'localhost';
FLUSH PRIVILEGES;
EXIT;
