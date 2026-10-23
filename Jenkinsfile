// Pipeline declarativo - ETL diario de ventas por local (caso academico Bembos)
// Jenkins en Windows (pasos "bat"). En Linux reemplazar "bat" por "sh".
pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 15, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    triggers {
        // Ejecucion diaria alrededor de las 6:00 a.m.
        cron('H 6 * * *')
    }

    environment {
        // Si defines PYTHON_EXE en Manage Jenkins > System > Global properties se usa esa ruta; si no, "python"
        PY            = "${env.PYTHON_EXE ?: 'python'}"
        PGHOST        = 'localhost'
        PGPORT        = '5432'
        PGDATABASE    = 'bembos_dataops'
        CORREO_EQUIPO = 'tu_correo@gmail.com'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Preparar entorno') {
            steps {
                bat '"%PY%" --version'
                bat 'if not exist venv "%PY%" -m venv venv'
                bat 'venv\\Scripts\\python -m pip install -r requirements.txt'
            }
        }

        stage('Pruebas') {
            steps {
                bat 'venv\\Scripts\\python -m pytest --junitxml=test-results.xml'
            }
            post {
                always {
                    junit 'test-results.xml'
                }
            }
        }

        stage('ETL ventas') {
            steps {
                // Usuario y clave de PostgreSQL guardados en las credenciales de Jenkins (id: postgres-local)
                withCredentials([usernamePassword(credentialsId: 'postgres-local',
                                                  usernameVariable: 'PGUSER',
                                                  passwordVariable: 'PGPASSWORD')]) {
                    bat 'venv\\Scripts\\python etl_ventas.py'
                }
            }
        }

        stage('Archivar resultados') {
            steps {
                archiveArtifacts artifacts: 'output/**', fingerprint: true
            }
        }
    }

    post {
        success {
            mail to: "${CORREO_EQUIPO}",
                 subject: "[OK] ETL Bembos - Build #${env.BUILD_NUMBER}",
                 body: "El pipeline termino correctamente.\nDetalle: ${env.BUILD_URL}"
        }
        failure {
            mail to: "${CORREO_EQUIPO}",
                 subject: "[FALLO] ETL Bembos - Build #${env.BUILD_NUMBER}",
                 body: "El pipeline fallo. Revisar la consola:\n${env.BUILD_URL}console"
        }
    }
}
