pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'BUILD_DOCKER',
            defaultValue: false,
            description: 'Run Docker image build after tests'
        )
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install dependencies') {
            steps {
                dir('backend') {
                    sh 'python -m pip install --upgrade pip'
                    sh 'python -m pip install -r requirements-dev.txt'
                }
            }
        }

        stage('Pytest') {
            steps {
                dir('backend') {
                    sh 'python -m pytest --cov=app --cov-report=term-missing --cov-report=xml -q'
                }
            }
        }

        stage('Docker build') {
            when {
                expression { params.BUILD_DOCKER }
            }
            steps {
                sh 'docker compose build backend'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'backend/coverage.xml', allowEmptyArchive: true
        }
        success {
            echo 'Backend tests passed.'
        }
        failure {
            echo 'Backend pipeline failed. Check the pytest output.'
        }
    }
}
