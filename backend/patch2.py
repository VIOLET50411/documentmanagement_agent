import sys
import re

path = '/app/app/api/v1/chat.py'
with open(path, 'rb') as f:
    content = f.read()

# We need to replace the session = ChatSession(...) with new_id logic
# Let's search for "session = ChatSession(id=str(uuid.uuid4())" using bytes
target = b'session = ChatSession(id=str(uuid.uuid4()), user_id=current_user.id, tenant_id=current_user.tenant_id, title=(first_question[:40].strip() or "'
if target in content:
    idx = content.find(target)
    # find the end of the line
    end_idx = content.find(b'\n', idx)
    original_line = content[idx:end_idx]
    
    replacement = b'new_id = thread_id if thread_id else str(uuid.uuid4())\n    session = ChatSession(id=new_id, ' + original_line.split(b'ChatSession(id=str(uuid.uuid4()), ')[1]
    
    new_content = content.replace(original_line, replacement)
    with open(path, 'wb') as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("TARGET NOT FOUND")
