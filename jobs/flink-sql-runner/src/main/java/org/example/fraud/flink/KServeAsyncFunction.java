package org.example.fraud.flink;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Collections;

import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.api.java.typeutils.ResultTypeQueryable;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.streaming.api.functions.async.ResultFuture;
import org.apache.flink.streaming.api.functions.async.RichAsyncFunction;
import org.apache.flink.types.Row;
import org.apache.flink.types.RowKind;

/**
 * Async I/O function that calls a KServe V2 inference endpoint for each transaction row and
 * appends {@code fraud_probability} (index 10) to the output Row. Uses the JDK built-in
 * {@link HttpClient} — no additional Maven dependency required.
 *
 * <p>On HTTP error or timeout the sentinel value {@code -1.0} is emitted so the pipeline
 * never stalls.
 *
 * <p>Input Row field positions (from {@code transactions} Iceberg table):
 * <pre>
 *   0  transaction_id  STRING
 *   1  user_id         INT
 *   2  amount          DOUBLE
 *   3  merchant        STRING
 *   4  lat             DOUBLE
 *   5  lon             DOUBLE
 *   6  ts              TIMESTAMP(3)  → LocalDateTime
 *   7  processing_time TIMESTAMP(3)  → LocalDateTime
 *   8  amount_velocity_5min   DOUBLE
 *   9  distance_from_home_km  DOUBLE
 * </pre>
 */
public final class KServeAsyncFunction
        extends RichAsyncFunction<Row, Row>
        implements ResultTypeQueryable<Row> {

    private static final long serialVersionUID = 1L;

    private final String endpoint;

    // transient: HttpClient is not serializable; rebuilt per task slot in open().
    private transient HttpClient httpClient;

    public KServeAsyncFunction(String endpoint) {
        this.endpoint = endpoint;
    }

    @Override
    public void open(Configuration parameters) {
        httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    @Override
    public void asyncInvoke(Row input, ResultFuture<Row> resultFuture) {
        double amount   = toDouble(input.getField(2));
        double velocity = toDouble(input.getField(8));
        double distance = toDouble(input.getField(9));

        String body = buildV2Payload(amount, velocity, distance);

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(endpoint))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

        httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                .whenComplete((response, ex) -> {
                    double prob = -1.0;
                    if (ex == null && response.statusCode() == 200) {
                        try {
                            prob = parseV2Response(response.body());
                        } catch (Exception ignored) {
                            // sentinel -1.0 already set
                        }
                    }
                    resultFuture.complete(Collections.singletonList(buildOutputRow(input, prob)));
                });
    }

    @Override
    public void timeout(Row input, ResultFuture<Row> resultFuture) {
        resultFuture.complete(Collections.singletonList(buildOutputRow(input, -1.0)));
    }

    @Override
    public TypeInformation<Row> getProducedType() {
        return Types.ROW_NAMED(
                new String[]{
                    "transaction_id", "user_id", "amount", "merchant",
                    "lat", "lon", "ts", "processing_time",
                    "amount_velocity_5min", "distance_from_home_km", "fraud_probability"
                },
                Types.STRING, Types.INT, Types.DOUBLE, Types.STRING,
                Types.DOUBLE, Types.DOUBLE, Types.LOCAL_DATE_TIME, Types.LOCAL_DATE_TIME,
                Types.DOUBLE, Types.DOUBLE, Types.DOUBLE
        );
    }

    private Row buildOutputRow(Row input, double fraudProbability) {
        Row output = Row.withPositions(RowKind.INSERT, 11);
        for (int i = 0; i < 10; i++) {
            output.setField(i, input.getField(i));
        }
        output.setField(10, fraudProbability);
        return output;
    }

    private static String buildV2Payload(double amount, double velocity, double distance) {
        return "{\"inputs\":[{\"name\":\"input-0\",\"shape\":[1,3],\"datatype\":\"FP64\","
                + "\"data\":[[" + amount + "," + velocity + "," + distance + "]]}]}";
    }

    /**
     * Extracts the first numeric value from a KServe V2 {@code "data":[...]} response field.
     * Avoids bundling a JSON library in the fat JAR to prevent Flink classloader conflicts.
     */
    static double parseV2Response(String body) {
        int dataIdx = body.indexOf("\"data\":[");
        if (dataIdx < 0) {
            throw new IllegalArgumentException("No \"data\":[ in response: " + body);
        }
        int start = dataIdx + "\"data\":[".length();
        // Skip any leading whitespace or nested '[' for batch shape
        while (start < body.length() && (body.charAt(start) == ' ' || body.charAt(start) == '[')) {
            start++;
        }
        int end = start;
        while (end < body.length() && body.charAt(end) != ',' && body.charAt(end) != ']') {
            end++;
        }
        return Double.parseDouble(body.substring(start, end).trim());
    }

    private static double toDouble(Object field) {
        if (field instanceof Double) return (Double) field;
        if (field instanceof Number) return ((Number) field).doubleValue();
        return 0.0;
    }
}
