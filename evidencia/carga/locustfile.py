from datetime import date, timedelta
import random

from locust import HttpUser, task, between


class SkillyUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        self.servicio_id = None
        self.token = None
        respuesta = self.client.get("/api/servicios/")
        if respuesta.status_code == 200:
            datos = respuesta.json()
            resultados = datos.get("results", datos) if isinstance(datos, dict) else datos
            if resultados:
                self.servicio_id = resultados[0]["id"]
        login = self.client.post(
            "/api/auth/token/",
            json={"email": "org@test.skilly", "password": "OrgTest123!"},
        )
        if login.status_code == 200:
            self.token = login.json().get("access")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _fecha_laborable(self):
        dia = date.today() + timedelta(days=random.randint(30, 60))
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        return dia.isoformat()

    @task(6)
    def catalogo(self):
        with self.client.get("/api/servicios/", catch_response=True) as respuesta:
            if respuesta.status_code != 200:
                respuesta.failure(f"catalogo {respuesta.status_code}")

    @task(3)
    def detalle_servicio(self):
        if self.servicio_id is None:
            return
        with self.client.get(
            f"/api/servicios/{self.servicio_id}/", catch_response=True
        ) as respuesta:
            if respuesta.status_code != 200:
                respuesta.failure(f"detalle {respuesta.status_code}")

    @task(3)
    def slots(self):
        if self.servicio_id is None:
            return
        with self.client.get(
            f"/api/servicios/{self.servicio_id}/slots/",
            params={"fecha": self._fecha_laborable()},
            catch_response=True,
        ) as respuesta:
            if respuesta.status_code != 200:
                respuesta.failure(f"slots {respuesta.status_code}")

    @task(1)
    def reserva(self):
        if self.servicio_id is None:
            return
        fecha = self._fecha_laborable()
        respuesta = self.client.get(
            f"/api/servicios/{self.servicio_id}/slots/",
            params={"fecha": fecha},
        )
        if respuesta.status_code != 200:
            return
        libres = [
            s["hora_inicio"]
            for s in respuesta.json().get("slots", [])
            if s.get("disponible")
        ]
        if not libres:
            return
        sufijo = random.randint(100000, 999999)
        with self.client.post(
            "/api/reservas/",
            json={
                "servicio": self.servicio_id,
                "fecha": fecha,
                "hora_inicio": random.choice(libres),
                "nombre": f"Carga {sufijo}",
                "email": f"carga{sufijo}@test.skilly",
            },
            headers=self._headers(),
            catch_response=True,
        ) as respuesta:
            if respuesta.status_code in (201, 400):
                respuesta.success()
            else:
                respuesta.failure(f"reserva {respuesta.status_code}")
