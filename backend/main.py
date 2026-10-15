from datetime import datetime
from typing import Optional
from fastapi import Body, FastAPI, HTTPException,status
from pydantic import BaseModel
import psycopg2,psycopg2.extras


app = FastAPI()

class Post(BaseModel):
    title : str
    content : str
    is_published : bool = False
    timestamp : datetime = datetime.now().time()
    

try:
    conn = psycopg2.connect(
        host = 'localhost',
        database = 'test',
        user = 'postgres',
        password = 'root',
        cursor_factory = psycopg2.extras.RealDictCursor
    )
    cursor = conn.cursor()
except:
    print("Unable to connect to the database")
    
    
@app.get('/')
def home():
    return {'message':"This is my first api"}

@app.get('/posts')
def retrieve_posts():
    cursor.execute("""SELECT * FROM posts""")
    my_post = cursor.fetchall()
    return {"data": my_post}

@app.get('/posts/{id}')
def retrieve_post(id:int):
    cursor.execute("""SELECT * FROM posts WHERE id = %s""",(str(id),))
    post = cursor.fetchone()
    if not post:
        return {"message":"post not found"}
    return {"data": post}
    

@app.post('/posts',status_code=status.HTTP_201_CREATED)
def create_post(post:Post):
    cursor.execute("""INSERT INTO posts (title, content, is_published, timestamp) VALUES (%s, %s, %s, %s) RETURNING *""",(post.title, post.content, post.is_published, post.timestamp))
    new_post = cursor.fetchone()
    conn.commit()
    return {"data": new_post}
    

@app.put('/posts/{id}',status_code=status.HTTP_204_NO_CONTENT)
def update_post(post:Post,id:int):
    cursor.execute("""UPDATE posts SET title = %s , content = %s , is_published = %s , timestamp = %s WHERE id = %s RETURNING *""",(post.title, post.content, post.is_published, post.timestamp, str(id)))
    updated_post = cursor.fetchone()
    conn.commit()
    if not updated_post:
        return {"message":"post not found"}
    
@app.delete('/posts/{id}',status_code=status.HTTP_204_NO_CONTENT)
def delete_post(id : int):
    cursor.execute("""DELETE FROM posts WHERE id = %s RETURNING *""" ,(str(id,)))
    deleted_post = cursor.fetchone()
    conn.commit()
    if not deleted_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )