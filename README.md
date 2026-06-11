services:

  elasticsearch:
    image: 

    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"

    ports:
      - "127.0.0.1:9200:9200"

    volumes:
      - elasticsearch-data:/usr/share/elasticsearch/data

    restart: unless-stopped

    networks:
      - dev-network

networks:
  dev-network:

volumes:
  elasticsearch-data:



curl -X PUT "http://localhost:9200/robot-keywords" -H "Content-Type: application/json" -d @robot-keywords-mapping.json