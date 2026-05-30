from ultralytics import YOLO
import cv2

model = YOLO("yolov8n.pt")

video_path = "data/videos/CAM 1.mp4"
cap = cv2.VideoCapture(video_path)
import time

visitor_start_time = {}

while True:
    ret, frame = cap.read()

    if not ret:
        break

    frame = cv2.resize(frame, (960, 540))

    results = model.track(
        frame,
        persist=True,
        classes=[0],
        conf=0.35,
        verbose=False
    )

    annotated = results[0].plot()

    if results[0].boxes.id is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy().astype(int)

        for box, track_id in zip(boxes, ids):
            if track_id not in visitor_start_time:
                visitor_start_time[track_id] = time.time()
            dwell_time = int(
                time.time() - visitor_start_time[track_id]
            )
            x1, y1, x2, y2 = box
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            center_x = int((x1 + x2) / 2)

            if center_x < 300:
                zone = "FACE_SHOP_ZONE"
            elif center_x < 650:
                zone = "SKINCARE_ZONE"
            else:
                zone = "MAKEUP_ZONE"

            label = (
                f"VIS_{track_id} | "
                f"{zone} | "
                f"{dwell_time}s"
            )

            print(f"VIS_{track_id} center_x={center_x} zone={zone}")

            cv2.putText(
                annotated,
                label,
                (x1, max(y1 - 15, 30)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            cv2.circle(
                annotated,
                (center_x, int((y1 + y2) / 2)),
                5,
                (0, 255, 255),
                -1
            )

    cv2.imshow("Zone Tracking", annotated)

    if cv2.waitKey(10) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()