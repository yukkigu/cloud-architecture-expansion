import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
    // num of virtual users to simulate
    vus: 20,
    // test duration
    duration: "60s",
    thresholds: {
        http_req_failed: ["rate<0.01"],
        http_req_duration: ["p(95)<500", "p(99)<1000"],
        checks: ["rate>0.99"],
    },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

export default function () {
    // Generate a unique item name for each request to avoid conflicts
    const itemName = `k6-item-${__VU}-${__ITER}-${Date.now()}`;

    // Simulate creating an item and then retrieving it
    const postRes = http.post(
        // goes to /items endpoint
        `${BASE_URL}/items`,
        JSON.stringify({ name: itemName, value: 123 }),
        { headers: { "Content-Type": "application/json" } }
    );

    // Check that the POST request was successful and returned a 201 status code
    check(postRes, {
        "POST /items is 201": (r) => r.status === 201,
    });

    // If the item was created successfully, attempt to retrieve it
    if (postRes.status === 201) {
        // get item id from response body
        const body = postRes.json();
        // goes to /items/{id} endpoint to retrieve the created item
        const getRes = http.get(`${BASE_URL}/items/${body.id}`);
        // ensure GET was successful and return 200 
        check(getRes, {
            "GET /items/{id} is 200": (r) => r.status === 200,
        });
    }

    // Simulate health check
    const healthRes = http.get(`${BASE_URL}/health`);
    // ensure health check endpoint is healthy and return 200
    check(healthRes, {
        "GET /health is 200": (r) => r.status === 200,
    });

    sleep(0.4);
}