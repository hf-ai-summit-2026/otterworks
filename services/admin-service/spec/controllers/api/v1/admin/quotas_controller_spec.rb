require 'rails_helper'

RSpec.describe Api::V1::Admin::QuotasController do
  before { set_jwt_env(request) }

  let(:user_id) { SecureRandom.uuid }
  let!(:quota) { create(:storage_quota, user_id: user_id) }

  describe 'GET #show' do
    it 'returns the storage quota for a user' do
      get :show, params: { user_id: user_id }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['user_id']).to eq(user_id)
      expect(body['tier']).to eq('free')
    end

    it 'returns 404 for unknown user' do
      get :show, params: { user_id: SecureRandom.uuid }
      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'PUT #update' do
    it 'updates the quota' do
      put :update, params: { user_id: user_id, quota: { tier: 'pro', quota_bytes: 214_748_364_800 } }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['tier']).to eq('pro')
    end

    it 'returns errors for invalid params' do
      put :update, params: { user_id: user_id, quota: { tier: 'invalid' } }
      expect(response).to have_http_status(:unprocessable_content)
    end
  end
end
