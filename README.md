{
  "keyword_name": "Start Semi Duplex PTT Call",
  "keyword": "",
  "file": "/xxx/xxxx",
  "scenario": "semi_duplex_ptt_call",
  "tags": [
    "ptt",
    "semi_duplex",
    "call",
    "voice"
  ]
}


curl -X POST "http://localhost:9200/robot-keywords/_doc" ^
-H "Content-Type: application/json" ^
-d @ptt-keyword.json



recherche 


{
  "query": {
    "match": {
      "keyword": "semi duplex ptt"
    }
  }
}

curl -X GET "http://localhost:9200/robot-keywords/_search?pretty" ^
-H "Content-Type: application/json" ^
-d @search.json
