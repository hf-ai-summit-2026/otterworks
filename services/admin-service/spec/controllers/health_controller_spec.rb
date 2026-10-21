require 'rails_helper'

RSpec.describe HealthController do
  describe 'GET /health' do
    it 'returns healthy status' do
      get :show
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['status']).to eq('healthy')
      expect(body['service']).to eq('admin-service')
    end
  end

  describe 'GET /metrics' do
    it 'returns prometheus metrics' do
      get :metrics
      expect(response).to have_http_status(:ok)
      expect(response.content_type).to include('text/plain')
      expect(response.body).to include('admin_service_up 1')
    end
  end
end
