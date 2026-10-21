require 'rails_helper'

RSpec.describe Api::V1::Admin::SettingsController do
  before do
    set_jwt_env(request)
    allow(AdminSettingsService).to receive(:set_auto_investigate)
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)
  end

  describe 'GET #auto_investigate' do
    it 'returns the current setting' do
      get :auto_investigate
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body).to eq('enabled' => false)
    end
  end

  describe 'PUT #update_auto_investigate' do
    it 'updates the setting' do
      put :update_auto_investigate, params: { enabled: 'false' }
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_auto_investigate).with(false)
    end

    it 'rejects a missing enabled parameter' do
      put :update_auto_investigate
      expect(response).to have_http_status(:bad_request)
      expect(AdminSettingsService).not_to have_received(:set_auto_investigate)
    end
  end
end
