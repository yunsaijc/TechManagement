import requests, json

filepath = '/home/tdkx/workspace/data/审查功能测试用典型项目信息/202520077/1757064464235.pdf'
with open(filepath, 'rb') as pdf:
    files_data = {'file': ('1757064464235.pdf', pdf, 'application/pdf')}
    data = {'document_type': 'award_contributor', 'enable_llm_analysis': 'true'}
    resp = requests.post('http://localhost:8888/api/v1/review', files=files_data, data=data, timeout=180)
    result = resp.json()
    print('status:', result['status'])
    for r in result['data']['results']:
        print(f'  {r["item"]}: {r["status"]} - {r["message"][:60] if r["message"] else ""}')
    llm = result['data']['llm_analysis']
    err = llm.get('extracted_fields',{}).get('error','none')
    print('extracted_fields error:', err[:80] if isinstance(err,str) else err)
    print('stamps:', llm.get('stamps_description'))
    print('units:', result['data']['extracted_data']['units'][:3] if result['data']['extracted_data']['units'] else '[]')