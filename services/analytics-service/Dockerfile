FROM sbtscala/scala-sbt:eclipse-temurin-jammy-17.0.10_7_1.9.9_3.4.1 AS builder

WORKDIR /app
ARG MAVEN_MIRROR=
RUN if [ -n "$MAVEN_MIRROR" ]; then printf '[repositories]\n  local\n  maven-mirror: %s\n  sbt-plugin-releases: https://repo.scala-sbt.org/scalasbt/sbt-plugin-releases/, [organization]/[module]/(scala_[scalaVersion]/)(sbt_[sbtVersion]/)[revision]/[type]s/[artifact](-[classifier]).[ext]\n' "$MAVEN_MIRROR" > /root/.sbt/repositories; fi
COPY build.sbt ./
COPY project/ ./project/
RUN sbt ${MAVEN_MIRROR:+-Dsbt.override.build.repos=true} update || true

COPY src ./src
RUN sbt ${MAVEN_MIRROR:+-Dsbt.override.build.repos=true} assembly

FROM eclipse-temurin:17-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/scala-3.4.0/analytics-service-assembly-*.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8088
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8088/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
