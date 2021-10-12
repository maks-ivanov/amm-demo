from time import time, sleep

from algosdk import account, encoding
from algosdk.logic import get_application_address
from amm.operations import createAmmApp, setupAmmApp, supply, withdraw
from amm.util import (
    getBalances,
    getAppGlobalState,
    getLastBlockTimestamp,
)
from amm.testing.setup import getAlgodClient
from amm.testing.resources import (
    getTemporaryAccount,
    optInToAsset,
    createDummyAsset,
)


def simple_auction():
    client = getAlgodClient()

    print("Alice is generating temporary accounts...")
    creator = getTemporaryAccount(client)
    supplier = getTemporaryAccount(client)

    print("Alice is generating example tokens...")
    tokenAAmount = 10 ** 13
    tokenBAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenBAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    poolToken = createDummyAsset(client, tokenAAmount, creator)
    print("TokenA id is:", tokenA)
    print("TokenB id is:", tokenB)
    print("Pool token id is:", poolToken)

    print(
        "Alice is creating AMM that swaps between token A and token B..."
    )
    appID = createAmmApp(client=client, sender=creator, tokenA=tokenA, tokenB=tokenB, poolToken=poolToken, feeBps=30)

    print("Alice is setting up and funding amm...")
    setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenQty=tokenAAmount,
    )

    creatorBalancesBefore = getBalances(client, creator.getAddress())
    ammBalancesBefore = getBalances(client, get_application_address(appID))

    print("Alice's balances: ", creatorBalancesBefore)
    print("AMM's balances: ", ammBalancesBefore)

    print("Supplying AMM with token A and token B")
    supply(client=client, appID=appID, qA=500_000, qB=100_000_000, supplier=creator)
    ammBalancesSupplied = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesSupplied)

    print("Withdrawing liquidity from AMM")
    withdraw(client=client, appID=appID, poolTokenAmount=1, withdrawAccount=creator)
    ammBalancesWithdrawn = getBalances(client, get_application_address(appID))
    print("AMM's balances: ", ammBalancesWithdrawn)
    # bidder = getTemporaryAccount(client)
    #
    # _, lastRoundTime = getLastBlockTimestamp(client)
    # if lastRoundTime < startTime + 5:
    #     sleep(startTime + 5 - lastRoundTime)
    # actualAppBalancesBefore = getBalances(client, get_application_address(appID))
    # print("The smart contract now holds the following:", actualAppBalancesBefore)
    # bidAmount = reserve
    # bidderAlgosBefore = getBalances(client, bidder.getAddress())[0]
    # print("Carla wants to bid on NFT, her algo balance: ", bidderAlgosBefore, " algos")
    # print("Carla is placing bid for: ", bidAmount, " algos")
    #
    # placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)
    #
    # print("Carla is opting into NFT with id:", nftID)
    #
    # optInToAsset(client, nftID, bidder)
    #
    # _, lastRoundTime = getLastBlockTimestamp(client)
    # if lastRoundTime < endTime + 5:
    #     sleep(endTime + 5 - lastRoundTime)
    #
    # print("Alice is closing out the auction....")
    # closeAuction(client, appID, seller)
    #
    # actualAppBalances = getBalances(client, get_application_address(appID))
    # expectedAppBalances = {0: 0}
    # print("The smart contract now holds the following:", actualAppBalances)
    # assert actualAppBalances == expectedAppBalances
    #
    # bidderNftBalance = getBalances(client, bidder.getAddress())[nftID]
    #
    # print("Carla's NFT balance:", bidderNftBalance, " for NFT ID: ", nftID)
    #
    # assert bidderNftBalance == nftAmount
    #
    # actualSellerBalances = getBalances(client, seller.getAddress())
    # print("Alice's balances after auction: ", actualSellerBalances, " Algos")
    # actualBidderBalances = getBalances(client, bidder.getAddress())
    # print("Carla's balances after auction: ", actualBidderBalances, " Algos")
    # assert len(actualSellerBalances) == 2
    # # seller should receive the bid amount, minus the txn fee
    # assert actualSellerBalances[0] >= sellerAlgosBefore + bidAmount - 1_000
    # assert actualSellerBalances[nftID] == 0


simple_auction()