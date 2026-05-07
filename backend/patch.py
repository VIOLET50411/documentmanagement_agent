import sys
path = '/app/app/api/v1/chat.py'
with open(path, 'r', encoding='utf-8', errors='surrogateescape') as f:
    content = f.read()

target = '    session = ChatSession(id=str(uuid.uuid4()), user_id=current_user.id, tenant_id=current_user.tenant_id, title=(first_question[:40].strip() or "新对话"))'
replacement = '    new_id = thread_id if thread_id else str(uuid.uuid4())\n    session = ChatSession(id=new_id, user_id=current_user.id, tenant_id=current_user.tenant_id, title=(first_question[:40].strip() or "新对话"))'

if target in content:
    content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8', errors='surrogateescape') as f:
        f.write(content)
    print('SUCCESS')
else:
    print('TARGET NOT FOUND')
