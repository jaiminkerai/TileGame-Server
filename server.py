# CITS3002 2021 Assignment
#
# This file implements a basic server that allows a single client to play a
# single game with no other participants, and very little error checking.
#
# Any other clients that connect during this time will need to wait for the
# first client's game to complete.
#
# Your task will be to write a new server that adds all connected clients into
# a pool of players. When enough players are available (two or more), the server
# will create a game with a random sample of those players (no more than
# tiles.PLAYER_LIMIT players will be in any one game). Players will take turns
# in an order determined by the server, continuing until the game is finished
# (there are less than two players remaining). When the game is finished, if
# there are enough players available the server will start a new game with a
# new selection of clients.
from itertools import cycle
from os import curdir, name
import socket
import sys

import tiles
import threading
import random
import queue
import time
import logging

class Player:
      def __init__(self, name, conn, id):
          self.name = name
          self.conn = conn
          self.id = id
      
class TileServer:
      def __init__(self):
          self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
          self.serveraddr = ('', 30020)
          self.clients = {}
          self.livePlayerids = []
          self.livePlayers = []
          self.ActiveGame = False
          self.GameBoard = tiles.Board()
          self.curTurn = None
          self.TokenMoves = []
          self.tileMoves = []
          self.curPool = None
          self.curChunk = False
          self.eventObj = threading.Event()
          self.__main__()

      def __main__(self):
            # initiate thread for handling clients joining 
            t = threading.Thread(target=self.listen, args=())
            t.start()

            # Game Loop
            while True:

                  # Initiates game and variables, based on starting conditions
                  while len(self.clients) > 1:
                        time.sleep(3)
                        self.GameBoard.reset()
                        self.curTurn = None
                        self.TokenMoves.clear()
                        self.tileMoves.clear()
                        self.sendCountdown()
                        time.sleep(10)
                        self.startGame()
                        time.sleep(1)
                        self.ActiveGame = False
                        print("GAME FINISHED")

      # The main game working function that operates a single game
      def startGame(self):
            players, pool, rand_order = self.findplayers()
            self.livePlayerids = rand_order
            self.livePlayers = players
            self.curPool = pool
            self.sendGameStart()
            self.sendInterface()
            self.sendPlayersTiles(players)
            self.ActiveGame = True  

            # loop for turn selection
            while len(self.livePlayerids) > 1:
                  time.sleep(0.5)
                  playerTurn = next(self.curPool)
                  while playerTurn not in self.livePlayerids:
                        playerTurn = next(self.curPool)
                  time.sleep(0.1)
                  self.sendPlayerTurn(playerTurn)
                  self.curTurn = playerTurn
                  buffer = bytearray()
                  TurnFinished = False
                  conn, __ = self.ClientInfo(playerTurn)
                  self.eventObj.clear()

                  # loop that continues until a given players turn is over or the player leaves
                  while len(self.livePlayerids) > 1:
                        try:
                              self.eventObj.wait(10)
                              chunk = self.curChunk
                              
                              if not chunk:
                                    TurnFinished = True
                                    self.eventObj.clear()
                                    time.sleep(0.2)
                                    break

                              buffer.extend(chunk)

                              while len(self.livePlayerids) > 1:
                                    msg, consumed = tiles.read_message_from_bytearray(buffer)
                                    if not consumed:
                                          self.eventObj.clear()
                                          break
                        
                                    buffer = buffer[consumed:]   
                                    print('received message {}'.format(msg))

                                    # sent by the player to put a tile onto the board (in all turns except their second)
                                    if isinstance(msg, tiles.MessagePlaceTile): 
                                          if self.GameBoard.set_tile(msg.x, msg.y, msg.tileid, msg.rotation, msg.idnum):
                                                TurnFinished = True

                                                # check for token movement
                                                positionupdates, eliminated = self.GameBoard.do_player_movement(self.livePlayerids)

                                                # update all players on moves made and eliminated players
                                                self.updatePlayers(msg, positionupdates, eliminated )

                                                # distirbutes a new tile 
                                                if playerTurn not in eliminated:
                                                      tileid = tiles.get_random_tileid()
                                                      conn.send(tiles.MessageAddTileToHand(tileid).pack())
                                                self.eventObj.clear()
                                                break

                                    # sent by the player in the second turn, to choose their token's starting path
                                    elif isinstance(msg, tiles.MessageMoveToken):
                                          if not self.GameBoard.have_player_position(msg.idnum):
                                                if self.GameBoard.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                                                      TurnFinished = True

                                                      # check for token movement
                                                      positionupdates, eliminated = self.GameBoard.do_player_movement(self.livePlayerids)

                                                      # update all players on moves made and eliminated players
                                                      self.updatePlayers(msg, positionupdates, eliminated)

                                                      # distirbutes a new tile 
                                                      if playerTurn not in eliminated:
                                                            tileid = tiles.get_random_tileid()
                                                            conn.send(tiles.MessageAddTileToHand(tileid).pack())
                                                      self.eventObj.clear()
                                                      break
                        except socket.timeout:
                              TurnFinished = True
                              self.eventObj.clear()

                        if TurnFinished:
                              self.eventObj.clear()
                              break

      
      # function called to return the information of a client, given thier id number
      # param: id number of client
      def ClientInfo(self, playerTurn):
            for player in self.livePlayers:
                  if player.id == playerTurn:
                        return player.conn, player.name

      # function called to send a countdown message to all clients
      def sendCountdown(self):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(tiles.MessageCountdown().pack())

      # function called to send an eliminated message to all clients   
      # param: playerTurn - the id of the player who has been eliminated
      def sendPlayerElim(self, playerTurn):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(tiles.MessagePlayerEliminated(playerTurn).pack())
            self.livePlayerids.remove(playerTurn)

      # function called to send board/tile/token updates to all clients
      # param: msg - the message sent by the player whose turn it was for tile movement
      # param: positionupdates - list of updates on players tokens
      # param: eliminated - list of players eliminated by the given move
      def updatePlayers(self, msg, positionupdates, eliminated):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(msg.pack())
                  for change in positionupdates:
                        conn.send(change.pack())
                  for player in eliminated:
                        conn.send(tiles.MessagePlayerEliminated(player).pack())
            for player in eliminated:
                  self.livePlayerids.remove(player)
            self.TokenMoves.append(positionupdates)
            self.tileMoves.append(msg)

      # function called to send a player left message to all clients
      # param: playerTurn - the id of the player who has left
      def sendPlayerLeft(self, playerTurn):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(tiles.MessagePlayerLeft(playerTurn).pack())

      # funcion caled to send all clients whose turn it is
      # param: playerTurn - the id of the player whose turn it is
      def sendPlayerTurn(self, playerTurn):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(tiles.MessagePlayerTurn(playerTurn).pack())

      # function called to distribute initial tiles to all players
      # param: players - list of all player objects in the game
      def sendPlayersTiles(self, players):
            for player in players:
                  conn = player.conn
                  for _ in range(tiles.HAND_SIZE):
                        tileid = tiles.get_random_tileid()
                        conn.send(tiles.MessageAddTileToHand(tileid).pack())
            

      # function called to send a game start message to all clients
      def sendGameStart(self):
            for __, client in self.clients.items():
                  conn = client.conn
                  conn.send(tiles.MessageGameStart().pack())

      def sendInterface(self):
            for __, client in self.clients.items():
                  for id in self.livePlayerids:
                        client.conn.send(tiles.MessagePlayerTurn(id).pack())

      # function called to send client on who else is in the game (both spectator and players)
      # param: player - a single player object who has joined the game
      def sendPlayersJoin(self, player):
            for __, client in self.clients.items():
                  conn = client.conn
                  if client != player:
                        conn.send(tiles.MessagePlayerJoined(player.name, player.id).pack())
                        player.conn.send(tiles.MessagePlayerJoined(client.name, client.id).pack())
                        
      # function called to send a welcome message to a single player
      # param: player - a single player object who has joined the game
      def sendWelcome(self, player):
            player.conn.send(tiles.MessageWelcome(player.id).pack())

      # function used to handle connections
      def listen(self):
            # create a TCP/IP socket
            sock = self.socket

            # listen on all network interfaces
            sock.bind(self.serveraddr)

            print('listening on {}'.format(sock.getsockname()))
            sock.listen(5)

            # counts for client ID
            clientID = 0

            while True:
                  # handle each new connection independently
                  connection, client_address = sock.accept()
                  print('received connection from {}'.format(client_address))
          
                  # adding client to dictionary
                  host, port = client_address
                  name = '{}:{}'.format(host, port)

                  # create new player object
                  p = Player(name, connection, clientID)

                  # add to clients list
                  self.clients[clientID] = p
                  clientID += 1

                  c = threading.Thread(target=self.checkClient, args=(p,))
                  c.start()

                  if self.ActiveGame:
                        self.handle_spectator(p)

      # function used to specifically handle clients who join mid-game and serve them information about the current game
      # param: client - a single player object who has joined the game
      def handle_spectator(self, client):
            time.sleep(1)

            # send client all eliminated players and all players in game
            for __ , player in self.clients.items():
                  if player in self.livePlayers:
                        client.conn.send(tiles.MessagePlayerTurn(player.id).pack())
                        if player.id not in self.livePlayerids:
                              client.conn.send(tiles.MessagePlayerEliminated(player.id).pack())
            
            # send client the turn of the player in current game
            client.conn.send(tiles.MessagePlayerTurn(self.curTurn).pack())

            # send client all token and tile information of current game
            for placements in self.tileMoves:
                  client.conn.send(placements.pack())
            for positionupdate in self.TokenMoves:
                  for changes in positionupdate:
                        client.conn.send(changes.pack())


      # function used to handle all connections of clients who join at anytime
      # param: player - a single player object who has joined the game
      def checkClient(self, player):
            self.sendWelcome(player)
            self.sendPlayersJoin(player)
            while True: 
                  try:
                        # recieving messages and processing 
                        chunk = player.conn.recv(4096)

                        # if its the players turn store this move
                        if player.id == self.curTurn:
                              self.curChunk = chunk
                              self.eventObj.set()

                        # handles when the client disconnects
                        if not chunk:
                              print('client {} disconnected'.format(player.name))
                              del self.clients[player.id]
                              if player.id in self.livePlayerids:
                                    self.sendPlayerElim(player.id)
                              self.sendPlayerLeft(player.id)
                              return
                  
                  except socket.timeout:
                        continue
                        

      # function used to determine a random play order 
      # return: player objects in order, cyclical list of ids of players, list of determined order
      def findplayers(self):
            if len(self.clients) >= 4:
                  rand_order = random.sample(self.clients.keys(), 4)
            else:
                  rand_order = random.sample(self.clients.keys(), len(self.clients))
            return [self.clients[x] for x in rand_order], cycle(rand_order), rand_order

def main():
      gameServer = TileServer()

if __name__ == "__main__":
      main()
