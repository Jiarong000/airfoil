from celery import Celery
import mysql.connector
import os
from minio import Minio
from datetime import timedelta
from minio.error import (ResponseError, BucketAlreadyOwnedByYou,
                         BucketAlreadyExists)

db_host = 'db'
db_user = 'root'
db_password = '123'

minioClient = Minio('data:9000',
                  access_key='minio',
                  secret_key='minio123',
                  secure=False)

celery = Celery(__name__, broker='amqp://airfoil:airfoil@broker/airfoil',backend='rpc://')

### Double check if database and table exists, else build it
db = mysql.connector.connect(
    host=db_host,
    user=db_user,
    password=db_password,
    autocommit=True
)
mycursor = db.cursor()

mycursor.execute('CREATE DATABASE IF NOT EXISTS airfoil')
mycursor.execute('''
            CREATE TABLE IF NOT EXISTS airfoil.results (
                id INT AUTO_INCREMENT PRIMARY KEY,
                angle FLOAT(20, 10),
                status TEXT,
                url TEXT
            )
        ''')

#to upload result to minio
def upload_result(angle):
    bucketname='angle'+str(angle)
    zipfile='./results.tar.gz'
    try:
        minioClient.make_bucket(bucketname, location="us-east-1")
    except BucketAlreadyOwnedByYou as err:
        pass
    except BucketAlreadyExists as err:
        pass
    except ResponseError as err:
        raise

    try:
        downloadurl=minioClient.presigned_put_object(bucketname, zipfile,expires=timedelta(days=3))
    except ResponseError as err:
        print(err)
    return str(downloadurl)



@celery.task
def calculate(id_, angle):
    print("Running task with id: " + str(id_))
    #update mysql status
    try:
        sql="UPDATE airfoil.results SET status = 'computing' WHERE id = '" + str(id_) + "'"
        mycursor.execute(sql)
    except:
        pass
        #sql = "INSERT INTO airfoil.results (angle, status, url) VALUES ("+str(angle)+", 'computing', 'url')"
        #mycursor.execute(sql)
        #db.commit()

    #generate mesh
    generate_mesh="cd ../murtazo/cloudnaca && ./runme.sh " + str(int(angle)) + " " + str(int(angle)) + " 1 200 3"
    os.system(generate_mesh)

    #convert mesh file
    meshfile='../murtazo/cloudnaca/msh/r2a'+str(int(angle))+'n200.msh'
    xmlfile='../murtazo/cloudnaca/msh/r2a'+str(int(angle))+'n200.xml'

    generate_xml='dolfin-convert '+meshfile+' '+xmlfile
    os.system(generate_xml)

    run_airfoil='../murtazo/navier_stokes_solver/airfoil  10 0.0001 10. 0.01 '+xmlfile
    os.system(run_airfoil)
    
    #zip result
    zipcommand='tar -zcvf results.tar.gz ./results'
    os.system(zipcommand)

    #upload to minio
    miniourl=upload_result(angle)

    #delete result folder and results.tar.gz
    os.system("rm -r results")
    os.system("rm -r results.tar.gz")

    #Update URL in db
    sql="UPDATE airfoil.results SET status='done' WHERE id = '" + str(id_) + "'"
    mycursor.execute(sql)

    sql="UPDATE airfoil.results SET url='" + str(miniourl) + "' WHERE id = '" + str(id_) + "'"
    mycursor.execute(sql)

    return miniourl

#calculate(12)
