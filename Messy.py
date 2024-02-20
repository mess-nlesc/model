import os
import time
import getpass
import paramiko
from stat import S_ISDIR, S_ISREG

# setup logging
paramiko.util.log_to_file("Messy.log")

class Messy:
    """This is a class to submit jobs to SLURM cluster
    """
    def __init__(self, username, hostname, port) -> None:
        self.username = username
        self.hostname = hostname
        self.port = port
        self.password = self.get_password()
        self.transport = self.set_transport()
        self.ssh_client = self.set_ssh_client()
        self.sftp_client = self.set_sftp_client()

    def get_password(self) -> str:
        """Sets user password"""
        password = getpass.getpass(f'password for {self.username}@{self.hostname}: ')
        return password

    def set_transport(self) -> paramiko.Transport:
        """
        Creates an paramiko transport
        """
        transport = paramiko.Transport((self.hostname, self.port))
        return transport

    def set_ssh_client(self) -> paramiko.SSHClient:
        """
        Creates an SSH client and connects to remote server
        """
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            self.hostname,
            port=self.port,
            username=self.username,
            password=self.password
        )
        return ssh_client

    def set_sftp_client(self) -> paramiko.SFTPClient:
        """
        Creates a SFTP client
        """
        self.transport.connect(
            username=self.username,
            password=self.password
        )
        sftp_client = paramiko.SFTPClient.from_transport(self.transport)
        return sftp_client

    def create_remote_folder(self, remote_folder: str) -> None:
        """
        Create a folder in the remote server
        """
        try:
            self.sftp_client.mkdir(remote_folder)
        except IOError:
            print(f"(assuming {remote_folder}/ already exists)")

    def get_files(self, remote_folder: str, local_folder: str = "./") -> None:
        """
        Get files from the remote server
        """
        if not os.path.exists(local_folder):
            os.mkdir(local_folder)

        for entry in self.sftp_client.listdir_attr(remote_folder):
            remotepath = remote_folder + "/" + entry.filename
            localpath = os.path.join(local_folder, entry.filename)
            mode = entry.st_mode
            if S_ISDIR(mode):
                try:
                    os.mkdir(localpath)
                except OSError:
                    pass
                self.get_files(remotepath, localpath)
            elif S_ISREG(mode):
                self.sftp_client.get(remotepath, localpath)

    def put_files(self, remote_folder: str = "~", local_folder: str = "./", verbose: bool = False) -> None:
        """
        Copy files to the remote server
        """
        if remote_folder == "~":
            remote_folder = os.path.expanduser("~")

        local_folder_dirname = os.path.dirname(local_folder)
        local_folder_basename = os.path.basename(local_folder)

        if verbose:
            print(f'local_folder_dirname: {local_folder_dirname}')
            print(f'local_folder_basename: {local_folder_basename}')

        for dirpath, dirnames, filenames in os.walk(local_folder):
            file_dirpath = dirpath[len(local_folder)+1:]
            remote_path = os.path.join(remote_folder, local_folder_basename, file_dirpath)
            if verbose:
                print('\n' + '-'*20 + '\n')
                print(f'dirpath: {dirpath}')
                print(f'dirnames: {dirnames}')
                print(f'remote_path: {remote_path}')
                print(f'file_dirpath: {file_dirpath}')

            try:
                self.sftp_client.listdir(remote_path)
            except IOError:
                self.sftp_client.mkdir(remote_path)

            for filename in filenames:
                path_1 = os.path.join(dirpath, filename)
                path_2 = os.path.join(remote_path, filename)
                self.sftp_client.put(path_1, path_2)
                if verbose:
                    print(f'\nfilename: {filename}  \n    path_1: {path_1}  \n    path_2: {path_2}')

    def submit_job(self, job_file: str) -> None:
        """
        Submit job to SLURM cluster
        """
        stdin, stdout, stderr = self.ssh_client.exec_command(f'sbatch {job_file}')
        job_id = int(stdout.read().decode().split()[-1])
        print(f'Submitted job with id: {job_id}')
        return job_id, stdin, stdout, stderr

    def check_queue(self) -> None:
        """
        Check job status
        """
        sleeptime = 0.001
        outdata, errdata = '', ''
        ssh_transport = self.ssh_client.get_transport()
        ssh_session = ssh_transport.open_session()
        ssh_session.settimeout(3 * 60 * 60)
        ssh_session.setblocking(0)
        ssh_session.exec_command('squeue --all')

        while True:  # monitoring process
            # Reading from output streams
            while ssh_session.recv_ready():
                stdout = ssh_session.recv(1000).decode("utf-8")
                outdata += stdout
                # print(stdout, end="")
            while ssh_session.recv_stderr_ready():
                stderr = ssh_session.recv_stderr(1000).decode("utf-8")
                errdata += stderr
            if ssh_session.exit_status_ready():  # If completed
                break
            time.sleep(sleeptime)

        return_code = ssh_session.recv_exit_status()
        ssh_transport.close()

        return return_code, outdata, errdata